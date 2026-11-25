# T-231: filing-level events from exchange announcements

Built 21 Nov 2026 by a dsh worker for ticket T-231 (Wolf 21 Nov, from Shivam's plan step 2; reviewer Wolf).
Stage A built the table; **Stage B** (after Wolf's read A: 37 right / 9 minor / 4 wrong of 50 verified) fixed the
nine named defect classes; **Stage C** (read B) adds the fund-raise stage/`raise_id`, the 120-day press-release
recap fold, the buyer/exploring/completion/borrowing vetoes, restatement dating, field hygiene and the multi-order
split. The factor study needs dated, quantified corporate events, one row per filing; T-228's generic claim
extractor over calls and annual reports restated facts across documents and stored parent-company facts under a
subsidiary.

Code `reality_engine/research/filing_events.py`; tests `reality_engine/tests/test_filing_events.py` (104 tests, no
network: stage-A real excerpts, stage-B/C/T-242 excerpts from the graded filings, and synthetic traps; every real
excerpt quotes its `doc_key`). Output DB `--out`, default `.tmp/t231/events.db`; stores are read with `connect_ro`
(`mode=ro`) and never written.

## 1. What the table is

`event` -- one row per (announcement, class, seq). Columns: `store`, `symbol`, `isin`, `doc_key`, `kind`, `method`
(`script` | `model`), `status`, `entity_scope`, `why`, `title`, `filing_date`, `event_date`, `known_at`, `page`,
`seq`, `amount_inr_cr`, `amount_usd_mn`, `value_text`, `value_annual`, `value_total`, `share_pct`, `customer`,
`customer_desc` (T-242 round 4: a printed category, never a named awarder),
`execution_months`, `order_kind`, `purpose`, `completion`, `capacity_value`, `capacity_unit`, `plant`,
`price_per_share`, `shares`, `instrument`, `raise_stage`, `raise_id`, `raise_primary`, `quote`, `amends`, `detail`;
`UNIQUE (doc_key, kind, seq)` is one event per filing per class, `seq` splitting a multi-order letter. `kind` is
`order_win`, `order_amendment`, `capex_approval`, `capacity_commissioned` or `fund_raise`.

`amend` -- a filing that names an earlier filing without being a new event: `doc_key`, `amends` (the earlier
`doc_key`), date and the words. Stage B uses it for the second copy of the same order (B2) and for a real
addendum/corrigendum.

`run_meta` -- the run counts, stop flag and model usage.

`known_at` is always copied from `doc`, never from the model. `filing_date` is the exchange filing date.

## 2. Classification (script, title + first two pages)

| kind | cue that fires | what is NOT an event |
|---|---|---|
| `order_win` | `pilot3.order_wins.parse` finds a win or the prescribed table, or a loose free-form letter with a win sentence and a printed "(e) Value" row | a court/tax/regulator order (incl. "penalty charged by GST department", "stay order", "writ"), a rumour clarification, a results release that mentions orders |
| `order_amendment` | a title/opening amendment/variation/extension cue **and** an order/contract word **and** a printed value or from-to phrase | a statement of deviation/variation, a credit-rating rationale, a termination/cancellation, a periodic utilisation statement |
| `capex_approval` | a clause carries a strong capex cue (capital expenditure/capex/expansion project/expansion at/of/greenfield/setting up) **and** an approval verb **and** the amount is printed | a board-meeting intimation, a deviation statement, a financial-statement note, "new line of business", a raise whose purpose is "to accelerate expansion" |
| `capacity_commissioned` | a completed commissioning cue and the added capacity with its unit in the same clause | EPC "supply, erection, testing and commissioning" scope; "expected/planned/approved/proposed to be commissioned" (a plan) |
| `fund_raise` | a raise cue (QIP, preferential, warrant, rights, NCD, borrowing, allotment/issue of shares) **and** an approval/done word, with a size or shares x price | board intimation "to consider fund raising", a credit-rating disclaimer, a SEBI framework circular, a SAST/open-offer advert by another party, ESOP/ESOS/RSU allotments |

A filing can carry one row per class (a bundled outcome that approves a capex and a raise yields two rows), never
two rows of the same class. Results/outcome filings are classified by the item that carries its own printed amount;
a financial-statement note on page 3+ cannot create a raise or a capex (the cue must be in the title + first two
pages). A stage-B rule: an unquantified "approved a capex plan" is not an event (it was the main false-positive
source in stage A).

## 3. Fields and printed-value check

* **Order wins** reuse `pilot3.order_wins.parse`; a free-form letter (`enter into a Contract Agreement ... (e) Value
  Rs. 67.96 Crores`) is read by `_loose_order_record`. Annual value (B4): "per annum"/"yearly"/"annually" with a
  printed tenure stores `value_annual` (the printed annual figure) and `value_total = annual x years` when the
  tenure is printed (computed -> `unverified`; no tenure -> the annual figure with a detail, still `unverified`).
  Monthly value is multiplied by the execution months. Consortium/JV (B5): when the filing prints the company's
  share (%, or the share amount), `amount_inr_cr` is the share, `share_pct` the printed percentage and
  `value_total` the printed total; a computed share is `unverified`. A doubled cover-letter + annexure figure is
  deduped before summing (B1). A new order stays `order_kind='new_order'` even when the press release also quotes
  the order book (B8). `order_kind` is `order_book_update` only for a pure order-book/intake update.
* **Order amendment** (B3): value = the printed increment (`from X to Y` -> Y-X, computed -> `unverified`) or the
  printed aggregate of distinct variation increments (e.g. "aggregate value ... Rs. 1,15,64,160"); an extension
  stores the printed contract value. `amends` links the nearest earlier order of the same symbol within 90 days
  when the old total or the customer matches.
* **Capex** is the approved amount; `from A to B` stores the **new** B; `purpose` is the full sanctioned clause;
  `completion` is the printed completion phrase.
* **Capacity** is the capacity added ("to 174 mtpa from 170 mtpa" -> 4 mtpa delta, `unverified`); "100 MT/M" keeps
  `mt_per_month`; `plant` comes only from a printed "at/in <Name>".
* **Fund raise** is the size, issue price, share count and instrument of **this step only** (`raise_step_amount`,
  round 5; structural rules in round 7): one printed total for the step ("aggregating to Rs X", "issue size Rs X",
  "for an aggregate consideration of", including an Indian-grouped figure whose currency mark the OCR dropped) or the
  securities THIS filing allots/converts x their issue price; a bundled outcome with two instruments sums their two
  printed totals (computed -> `unverified`). Never added: the green shoe inside "up to X including", a premium, a base
  issue, cash/balance consideration, a partly-paid tranche, the 25% upfront and 75% balance of a warrant, an earlier
  step's aggregate, a past year's figure, a cumulative "till date" count and the paid-up capital before or after the
  issue (rounds 5 and 7). A converted security is priced itself (CCDs x their issue price), not the post-split shares
  it becomes; a filing whose subject line names the allotted count ("Allotment of 75,000 Equity shares upon conversion
  of warrants") takes that count x price. Stage B
  fixed the wrong-item case (SHREEPUSHK: the 350 cr capex is capex, the raise is 7,36,196 warrants x 407.5 = 30 cr,
  computed; SPMLINFRA: preferential 5.75 + warrants 177.43 + shares 7.16 = 190.34 cr, computed).
* Every figure carries the exact printed span (`value_text`), its page (0 = the exchange headline) and the sentence
  (`quote`). `_locate` matches the number against the page's own money/capacity spans, accepting the printed
  full-rupee form and a "crore"-suffixed full figure (`Rs. 7,40,06,30,000 Crore` -> 740.063 cr).

Status (T-242 round 3, 24 Nov 2026; scope and L1 in round 6; the step's amount/issuer/stage in round 7): `verified` =
every field printed, scope company or
`subsidiary` (a subsidiary's order keeps its status with the printed name in `detail`), no `l1_only` veto, **and the
row's kind is in `VERIFIED_KINDS`** (`frozenset({"order_win"})`; `_gate_status`, then `_finish_scope`); `unverified` =
a computed figure, an amount the script could not fill, a parent-scope row, an L1-only intimation
(`why='l1_only'`), or a kind that has not passed its own fresh strict 60-row grade (detail
`kind_not_gated: <kind> awaits its own 60-row grade`); `quarantined` = the value is not on the page. A kind joins
`VERIFIED_KINDS` only after its own fresh 60-row grade, so `fund_raise`, `capex_approval`,
`capacity_commissioned` and `order_amendment` rows are never verified until then. Run 24 Nov 2026 on the 20 fresh3
stores: 251 events, 0 quarantined, no non-order row verified. Round 6 re-measured the same two sets (25 fresh4 + 20
fresh3 stores): no graded R row changed status or amount. Round 7 re-graded all 60 fresh5 rows (all right, 0 R moved)
and re-ran fresh4/fresh3: no graded R row changed, and verified `order_win` stayed 215 fresh5 / 132 fresh4 / 179
fresh3.

## 3b. Stage C rules

* **C1 fund-raise stage.** `raise_stage` is `proposed`, `approval`, `allotment`, `listing` or `completion`, read
  from the title/subject and opening, applied in this order (round 5): a completed allotment -> `allotment`; a
  postal-ballot or EGM notice -> `proposed`; a board that approved only a draft notice -> `proposed`; a board or
  shareholder approval of an issue -> `approval`; an exchange in-principle approval -> `approval`; a listing/trading
  approval -> `listing`; an issue opened/closed/fully subscribed -> `completion`. `intimation` is not a stage.
  `_assign_raise_ids` groups rows into one raise by symbol, instrument family, size within
  5% (a same-day 2x print is the same raise) and 365 days; `raise_id` is the same across stages and exactly one row
  per id has `raise_primary=1` (allotment > completion > approval > listing > proposed; earliest on a tie).
  Factors select `raise_primary=1`. This run: 157 raise ids, 157 primaries; the JYOTISTRUC 500 cr rights has five
  dated rows (approval Nov 2024, allotment Mar 2025) under one id and one primary.
* **C2 recap fold.** The same order 8-120 days later (press release recapping an earlier disclosure) folds only
  when the value repeats within 0.05% or the later text names the earlier filing date, plus the same customer;
  within 7 days the 0.5% rule stands (round 4; the round-3 note said 1%, the code used 0.005), and a customer
  printed once in full and once as its initialism (`TPSODL and TPWODL`) is the same customer. Different customers
  stay separate (KRYSTAL 551/556, ABINFRA 397/439); the later document goes to `amend`.
* **C3 vetoes.** "Completion of project/order"; "exploring", "to consider", "proposal to", "enabling resolution",
  borrowing limits (capex and raises); a buyer-side EPC contract ("signed/entered into ... EPC contract ...
  with", "EPC contract to be entered into between"); "ballot" never matches allotment (the recall title filter
  excludes it).
* **C4 restatement dating.** A capacity event narrated as background in a later filing is dropped when an earlier
  capacity row of the same symbol/value exists (GREENPOWER's 7 MW December commissioning in a July allotment
  filing); a first disclosure keeps the printed `event_date`.
* **C5 field hygiene.** Customer must be a named entity (dates, "letter of acceptance", "order(s)", "the company"
  are rejected); shares are a count, never authorised/paid-up capital, post-issue total, face value or a ratio
  ("9 for every 26"); an equity + warrant issue sums the distinct counts; a letter with two orders gives two rows
  (`seq` 1, 2), and a fresh LOA plus a variation gives one row each.

## 3c. T-242 round 4 (24 Nov 2026): customers, roll-ups, aggregates, duplicates

Eagle review of round 4: the city cut applies only after a company's legal suffix (Limited, Ltd, LLP); after a public body's word (Corporation, Nigam, Authority, Railway, Division) only a comma cuts, so "Municipal Corporation Jodhpur" keeps its name (test `test_t242_city_after_company_suffix_cut_but_public_body_name_kept`).

Seven script fixes from the second fresh strict 60-row grade (25 unseen stores:
`C:/RealityEngine/t242/events_grade_fresh4/grades.csv`, R/P/W/J = 46/11/2/1, 5.0% W+J at the bar). Each fix is
asserted by a test in `test_filing_events.py`.

1. **Customer clean-up in one place** (`_clean_party`). A trailing salutation (`Dear Sir/Madam`, `Respected
   Sir/Ma'am`) and a trailing city/address after a legal suffix (`Signatureglobal (India) Limited Mumbai` ->
   `Signatureglobal (India) Limited`) are cut; `_ANNEXURE_AWARDER` may no longer begin a name inside a word
   (`\s*(?<!\w)` before the captured name). The **cause** of `uth Central Railway` was not this module but
   `pilot3/order_wins.py` `_OC`: the trailing `(?:\s?\(?s\)?)?` after `Order/Contract` consumed the space and the
   `S` of the next word. The plural is now attached or bracketed (`(?:\s*\(\s*s\s*\)|s)?`) and the trailing junk
   character is punctuation-only (`[^\w\s]?`), so `order(s)` / `orders` / `Order/Contract X` all end at the value.
   `_FROM_ENTITY` accepts one bracketed token (`GAIL (India) Limited`, fresh4 #24) and the body-name capture no
   longer runs across a `|`-separated headline.
2. **`customer_desc`** (new nullable `event` column; `COLUMNS`, `SCHEMA`, and `_ensure_event_columns` which adds it
   to an older `--baseline` copy before a scoped merge). A customer value that is all lower case or starts
   `a|an|leading|key|domestic|customers|clients|one of|...` is a description, not an awarder; `_split_customer`
   moves it out and leaves `customer` NULL (`A hyperscale partner`, `Domestic Telecom Operator`, `Leading telecom
   infrastructure company`, `key customers in the renewable energy sector`). It runs on script and model rows.
3. **Period roll-up veto** (`_ORDER_ROLLUP`): `awarded orders worth X in FY24`, `orders received during the
   year/quarter` are aggregates, not an order (fresh4 W #51: 900 cr "awarded in FY24"). `order inflow/intake for
   FY` is read on the **title only** (`_ORDER_INFLOW_TITLE`): a genuine order-win release (KEC, TRANSRAILL) quotes
   its own order inflow in a later paragraph, and vetoing the body would drop the real order (round-4 regression,
   fixed before the final run).
4. **Title aggregate over a split table** (`_FILING_TOTAL` full-rupee branch + `order_fields`). When the title
   prints the aggregate and the table prints one item of it, the row is the printed aggregate: SUGSLLOYD's title
   214.27 crore with table cells 115.0194 + 99.2543 (fresh4 W #38) is now one verified row of 214.27, not the first
   cell. The body's "aggregate order value ... is ₹ 2,14,27,36,930/-" is the printed confirmation; no printed
   aggregate, no correction.
5. **Cross-filing duplicate** (`_same_customer`): a customer printed once in full and once as its initialism
   (`TPSODL and TPWODL` vs `TP Southern Odisha Distribution Limited TP Western Odisha ...`) is the same customer,
   so the next-day press release (fresh4 J #44) folds into the earlier row through the existing 7-day,
   `_same_value` 0.5% path and lands in `amend`. A token-subset rule was tried and removed: it folded graded R #7
   (`Golden Temple`, 8.9 cr) into a different 3.7083 cr row whose `value_annual` is 8.9.
6. **Tests.** Six new cases in `test_filing_events.py` (one per step, from the quoted rows); 85 passed.
7. **Measured** on the 25 fresh4 stores before -> after: 303 -> 301 events, `order_win` verified 133 (97 script +
   36 model) -> 132 (96 + 36); one quarantined SUGSLLOYD row became verified when the same aggregate rule fixed
   its 0.0047 -> 4.68 cr reading; the two lost rows are the intended W #51 (roll-up) and J #44 (duplicate folded).
   All 11 P customer rows are correct (7 needed: 2 leading cuts, 3 salutations, 1 city, 1 pattern miss -> 5
   descriptions moved to `customer_desc` and the GAIL name found), and **no graded R row changed amount, customer
   or status**. On the 20 fresh3 stores the round-3 result is unchanged: 251 events, `order_win` verified 193, 0
   rows lost vs `events_round3.db`, only customer clean-ups changed.

## 3d. T-242 round 5 (24 Nov 2026): this step's amount, the stage map, duplicates, vetoes

Third fresh strict 60-row grade of `fund_raise` alone, on 45 stores neither earlier round was tuned on
(`C:/RealityEngine/t242/events_grade_fundraise/grades.csv` + `pack.jsonl`; DeepSeek a8f57918: 30 R / 16 P / 10 W /
4 J). Eight script fixes, each asserted by a test in `test_filing_events.py`. `VERIFIED_KINDS` and the `order_win`
logic are untouched: `fund_raise` is still stored `unverified` (`kind_not_gated`).

1. **The step's own amount** (`raise_step_amount(text) -> (amount_cr, how)`, pure; the shared clause reader is
   `_raise_step_sizes`). The event amount is what THIS step printed: its one total ("aggregating to Rs X", also when
   the OCR dropped the currency mark and the figure is Indian-grouped) or the shares it issued x the issue price.
   Before: 1,140.2161 cr on a QIP that printed 1,85,49,99,790 (the paid-up share count was also multiplied by the
   price). After: 185.5.
2. **Components are never added** (`_RAISE_COMPONENT` window around a printed figure: 25%/75%, the remaining
   exercise price, an equivalent amount). A warrant conversion that printed 8,00,000 shares at Rs 124 and the
   Rs 4,65,00,000 25% receipt of the earlier subscription is Rs 9.92 cr, not 14.57 (#12, #20, #57: 7.0 and 4.0);
   the 75% balance is the component of #13's 3,52,941 x 425 = 15.00 cr, not the 500 cr of the December warrant
   allotment.
3. **Earlier steps and capital are cut, not summed** (`_RAISE_PRIOR_STEP`: `had allotted`, an earlier/previous
   issue, `in the FY 2014-15`; `_RAISE_CAPITAL`: paid-up capital before/after the issue, pre/post-issue). The clause
   is cut at the cue so a genuine total printed before it survives: #32 stores the Rs 500 crore enabling resolution
   (not 850), #54 the 10,000.00 million QIP (not +602.83 million of pre-issue capital), #10 185.5.
4. **Vetoes** (`_RAISE_SUBSIDIARY_VETO`, `_RAISE_ADVISORY_VETO`, `_RAISE_GENERIC_CUE` without `_RAISE_SECURITY`):
   a subsidiary that "has allotted" its own rights shares (the listed company issued nothing), an exchange advisory
   or lock-in letter about an earlier issue, and "fund raising through debt" with no security named are not
   issuances (#19, #21, #43 gone).
5. **Stage map** (`_raise_stage`, `_ALLOTMENT_DONE`, `_RAISE_NOTICE`, `_RAISE_NOTICE_DONE`, `_RAISE_DRAFT_ONLY`,
   `_RAISE_IN_PRINCIPLE`, `_RAISE_LISTING`, `_RAISE_COMPLETION`): a committee that "allotted 300 NCDs" or "considered
   and approved the allotment of 1,19,99,847 Equity Shares" completed the allotment; a postal-ballot or EGM notice
   subject line -> `proposed` (a board outcome that merely lists the EGM notice among its resolutions approved the
   issue); "approved the draft Postal Ballot Notice" alone -> `proposed`; an exchange in-principle approval ->
   `approval`, never `listing`; `intimation` is gone. 13/13 stage rows right (#1, #5, #6, #7, #23, #25, #31, #33,
   #40, #46, #49, #51, #53).
6. **Duplicates** (`_fold_same_raise`, wired into `build` after `_fold_same_order`): a press release, errata or
   second letter repeating a step is one event — same company, an amount within 0.5% or the same printed share
   count, within 10 days — and the repeat names the kept row in `amend` (#9, #29, #48, #60). Two letters filed the
   same day about one step keep the more advanced stage (the QIP allotment over the board's allocation letter); a
   notice, and a later stage on a later day, are never folded.
7. **Tests**: `test_t242_r5_raise_step_amount_is_this_step_only` (six quoted shapes: the QIP total without its
   currency mark, the 25% receipt, a part conversion, the 75% balance, the millions figure, the enabling
   resolution), `test_t242_r5_a_bundled_board_approval_still_adds_its_two_instruments`,
   `test_t242_r5_raise_stage_map` (six stages), `test_t242_r5_not_an_issuance` (three vetoes),
   `test_t242_r5_a_press_release_repeating_an_allotment_folds`,
   `test_t242_r5_a_notice_and_a_later_step_do_not_fold`; `test_stage_c_ballot_is_not_an_allotment` now expects
   `proposed`. 104 passed (86 before).
8. **Measured** (cache `C:/RealityEngine/t242/events_cache.db` copied to `.tmp/events_cache.db`, 0 new model
   requests). On the 25 fresh4 stores: 301 -> 290 events, `fund_raise` 86 -> 75 rows (all `unverified`),
   `amend` links 27 -> 63 (36 raise folds), `order_win` verified 132 (96 script + 36 model) unchanged. On the 20
   fresh3 stores: 251 -> 249 events, `fund_raise` 36 -> 34, `amend` 30 -> 39, `order_win` verified 193 unchanged.
   Across the 60 graded rows: 30/30 R rows unchanged in amount, stage and status; 7/7 amount W fixed, 3/3
   not-an-issuance W gone; 4/4 J folded with an `amend` link; 13/13 stage P right. A few ungraded rows also moved
   (intended): a subsidiary's cessation notice, an exchange advisory and a limit-revision letter were folded or
   dropped, and 23 stage labels changed with the map. DBs `.tmp/events_r5_fresh4.db`, `.tmp/events_r5_fresh3.db`;
   reports `.tmp/events_r5_fresh{4,3}_report.md`.
9. **Deliberate ceilings.** The component rule keys on a percentage or the remaining-exercise-price wording near
   the figure, so a filing that prints only the 75% balance and no percentage keeps the printed balance (#22, #41,
   #45 are the graded R rows and stay at 3.6806, 3.9 and 5.7647 cr). The fold needs the same amount within 0.5% (or
   the same share count), so a repeat whose number was read differently stays two rows; it never merges an approval
   with its later allotment.

## 3e. T-242 round 6 (25 Nov 2026): L1-only, subsidiary scope, headline customer

A surprise strict audit of 60 **verified** `order_win` rows from the round-5 DBs
(`C:/RealityEngine/t242/audit_orderwin_r5/`, DeepSeek b87f8d84) scored **52 R / 0 P / 8 W / 0 J**: 13% wrong among
verified rows, against the 5% bar. Three script causes, fixed in `reality_engine/research/filing_events.py`; no
`fund_raise` logic and no `VERIFIED_KINDS` change.

1. **L1-only is not an order yet** (`_LOWEST_BIDDER` now also reads "emerged as L1"; `_AWARD_RECEIVED`, `_l1_only`,
   applied by `_finish_scope` at both status sites). When the title/subject or the first 600 characters say lowest
   bidder / L-1 / L1 status and no LoA, work order or contract award is ALSO stated as received, the row keeps its
   printed value but is stored `unverified` with `why='l1_only'` (detail names the rule). A received LoA wins even
   when the same document mentions L1 (audit #26 Kolkata Municipal Corporation; fresh3 #28 KMEW "emerged as the
   lowest bidder" after the LoA). 13 fresh3 verified rows unverified, all EMSLIMITED; 0 on fresh4. Measured stop
   (agy 70ccab33): 13/193 = 6.7%, under the 15% line.
2. **A subsidiary's order is a real order for the group** (`_subsidiary_name`; `_SUB_AFTER_NAME`, `_SUB_BEFORE_NAME`,
   `_SUB_NAME_STOP`, `_SUB_GENERIC`, `_SUB_JUNK`, `_SUB_SUFFIX`; called from `blank_row` for `order_win` only). When
   the order sentence's subject is a NAMED subsidiary ("<Name>, a wholly owned subsidiary of the Company, has
   received", "our subsidiary <Name>", "material subsidiary, <Name>", "subsidiary - <Name>", "US-based subsidiary
   <Name>", "our subsidiary, <Name>, has secured", and the printed "subsdiary" typo), the row KEEPS its status and
   gets `entity_scope='subsidiary'`; the name is the one printed in the filing, stored in `detail` as
   `subsidiary: <name>` (`detail` is free text, not JSON; the choice the brief asked us to report). A filing that says
   only "a subsidiary"/"received by subsidiary company" without a name keeps `entity_scope='company'` (Wolf, 25 Nov).
   A third party's subsidiary is the customer, not the issuer's scope ("TenX Realty Limited, (a step-down subsidiary
   of Raymond Limited)"). 67 fresh4 + 9 fresh3 rows labelled; no status or amount moves for this rule.
3. **A press-release headline is not the customer** (`_HEADLINE_CUSTOMER`, `_HEADLINE_PLACE` in `_clean_party`): a
   customer carrying a headline verb, a month with a day, or an all-caps place + date ("BSNL to Power India's
   Telecom Future BANGALORE - January 01") is rejected; the existing body-name fallback then finds "Bharat Sanchar
   Nigam Limited (BSNL)".

Measured on the same stores into new DBs (cache `C:/RealityEngine/t242/events_cache.db` copied to `.tmp/events_cache.db`,
0 new model requests; `.tmp/events_r6_fresh4.db`, `.tmp/events_r6_fresh3.db`):

* **All 8 W rows** are no longer verified-and-wrong: #7 and #32 are `unverified` / `why='l1_only'`; #24, #37, #42, #49
  and #58 are `entity_scope='subsidiary'` (status verified) with printed names Provigil Surveillance Limited (x2),
  EFC Limited, Lineage Power Private Limited and Aurionpro Fintech Inc; #54 (the headline-customer row) is gone
  because its row now names the same BSNL and the same 94.35 cr as the earlier `5d19a5c9` filing (94.3513 cr,
  `entity_scope='subsidiary'`), so B2 folds it into that verified row and links it in `amend`.
* **No graded R row changes status or amount**: 52/52 audit R, 46/46 `events_grade_fresh4` R and 41/41
  `events_grade_fresh3` R. The only non-R status change is one graded P row (`events_grade_fresh3` #23, the
  EMSLIMITED L-1 104.0552 cr row, now `l1_only`).
* **Verified `order_win` counts**: fresh4 132 -> 132 (96 script + 36 model); fresh3 193 -> 179 (172 script + 7 model;
  13 verified -> `unverified` all `l1_only`, and 1 row fewer because the #54 press release folded). Rows newly
  labelled `entity_scope='subsidiary'`: 67 on fresh4, 9 on fresh3; among graded rows, 9 of the audit (4 R), 12 of
  `events_grade_fresh4` (9 R) and 2 of `events_grade_fresh3` (2 R).
* **Tests**: `test_t242_r6_an_l1_only_intimation_is_unverified_but_a_received_award_stays`,
  `test_t242_r6_a_subsidiary_order_is_labelled_and_keeps_its_status` (five quoted shapes + the unnamed and the third
  party's subsidiary) and `test_t242_r6_a_press_release_headline_is_not_the_customer` (audit #54);
  `test_t242_r3_fix4_l1_and_loss_reduction_are_awards` now expects the L1 half `unverified`/`l1_only`. 107 passed at
  round 6 (121 after round 7).
* **Deliberate ceilings.** The scope test is document-level, not sentence-level: an order the issuer *received
  from* its own subsidiary would be labelled `subsidiary` too (rare; the related-party crop is small). A subsidiary
  whose parent is named rather than "the Company" is rejected as a name-before-marker match and recovered by the
  marker-before-name shape where the filing prints one; where it does not, the row stays `company`. No company name
  is in the code (patterns only).

## 3f. T-242 round 7 (25 Nov 2026): the step's own amount, the issuer, the stage

Round 5 fixed all 30 failing rows of its own graded 60; a strict grade on 40 UNTUNED stores (fresh5,
`C:/RealityEngine/t242/events_grade_fundraise_fresh5/`) then read **31 R / 7 P / 22 W / 0 J**: round 5 had fitted
rows, not the kind. Four structural rules now hold on unseen filings; `VERIFIED_KINDS` and the `order_win` path are
untouched (`fund_raise` stays `unverified`).

1. **The listed company is the issuer** (`_RAISE_FOREIGN_ISSUE_VETO`, read on title + first two pages). A raise
   needs the listed company to allot or issue the security, so these are not raises: a subscription to another
   entity's rights issue ("subscription to Rights issue of <subsidiary>"), an investment in or acquisition of another
   company's shares (cash or share swap, "strategic investment by acquisition of N shares"), a subsidiary's or
   associate's own allotment (also when the security is allotted TO the listed company), a loan granted to a
   subsidiary ("loan agreement", "unsecured loan"), a sale/divestment of a stake paid in another company's paper
   ("issuance of <Name>'s CCPS"), and "right to invest" / "co-invest" / "invested ... in <Name> Limited".
2. **The step's amount** (`_raise_size`, `_raise_count_size`, `_raise_step_sizes`). In this order: the printed total
   of THIS step ("aggregating to", "total aggregating to", "issue size", "for an aggregate consideration of"), else
   the securities ALLOTTED IN THIS FILING times the issue price of the security being allotted or converted. A
   component never adds: the green shoe ("up to X including a green shoe option of Rs Y": X is the amount), a
   premium/accrued interest, a base issue, cash/balance consideration of an acquisition, a partly-paid tranche
   (`_RAISE_COMPONENT_BEFORE` reads the prefix the cue governs, so "including a premium ..., aggregating to Rs X"
   keeps X). Not the step: a clause recording an earlier step ("pertaining to the allotment of", "till date",
   "after this allotment", "out of the balance"), an allottee that fell away ("became ineligible"), and a
   balance/instalment receipt ("remaining 75% amount", "balance subscription amount", 25%/75% of the issue price)
   (`_RAISE_PRIOR_STEP`, `_RAISE_NOT_STEP`, `_RAISE_BALANCE_CLAUSE`). A converted security is priced itself:
   1,45,010 CCDs x Rs 1,00,000, not the 10,32,09,960 post-split shares x their conversion price
   (`_raise_instrument`, `_instrument_price`). The subject line's own allotment count wins ("Allotment of 75,000
   Equity shares upon conversion of warrants" -> 75,000 x the warrant issue price), a filing that reports two
   instruments still sums their two printed totals, and a printed total beats a computed one.
3. **The stage** (`_raise_stage`). A board recommendation to seek members' approval (`_RAISE_RECOMMEND`) and a
   resolution to be passed at the AGM or the AGM's own business ("for raising of funds", `_RAISE_AGM_AGENDA`) are
   `proposed`; the proposed "issue and allotment of N warrants" item is no longer read as a completed allotment
   (`_ALLOTMENT_DONE` needs "considered and approved the allotment of N"); a press release that says the issue was
   successfully concluded/closed is `allotment` (`_RAISE_CONCLUDED`).
4. **A size belongs to the row's instrument** (`_raise_family_ok`): a QIP notice that also prints an NCD
   resolution's Rs 500 cr does not take the NCD amount, while a filing that approves two instruments still adds.

Measured on the 40 fresh5 stores into a new DB (cache `C:/RealityEngine/t242/fresh5/events_cache.db` copied to
`.tmp/events_cache.db`, 0 new model requests; `.tmp/events_r7_fresh5.db`):

* **All 60 graded rows are right** (round 7 code, read back through `event_rows` on the graded doc_keys, then the
  full rebuild): 31/31 R amounts and stages unchanged; 15 W amounts fixed (#2 2375 -> 1875, #5 1080.57 -> 346.606,
  #6 800 -> 808, #7 3.111 -> 3002.10466, #16 26 -> 474.006, #17 294.327 -> 2.2275, #19 514.404 -> 196.02,
  #21 133.947 -> 5.643, #23 1500 -> 1450.1, #31 121.3245 -> 6.831, #32 0.5 -> 25.6875, #41 703.89 -> 326.7,
  #49 823.84 -> 700, plus #45 and #60 gone: their QIP prints no rupee size and the NCD/acquisition figure is not
  the QIP's); 7 W no longer raises at all (#10, #14, #24, #29, #33, #38, #50); 6 P stages fixed (#11, #47, #59
  -> `proposed`; #22, #51 -> `approval`; #55 -> `allotment`); #27 keeps its R amount.
* **`order_win` verified count unchanged at 215** (195 script + 20 model; the same 12 companies); `model_requests`
  0 (the copied cache answered every pending filing). `fund_raise` events 150 -> 136 (the 7 vetoes, #45/#60 gone,
  and fewer duplicate prints after the instrument-scoped sizes); 16 quarantined (the #7 total now printed at
  3002.10466 cr does not match a `_locate` span on its page).
* **fresh4/fresh3 re-run** (same caches; the fresh4 run needs `MODEL_STOP_SHARE` raised to 0.5 for the measurement
  only because 30.18% of the new pending filings cross the 30% stop): verified `order_win` fresh4 132 (unchanged),
  fresh3 179 (unchanged, 0 new model requests). `fund_raise` rows that changed amount/stage or went: fresh5 54/150
  (36.0%), fresh4 24/75 (32.0%, 14 changed + 10 removed), fresh3 7/34 (20.6%, 3 changed + 4 removed). **Reported
  over the brief's 25% stop line on fresh4/fresh5**: the moved rows are the same shapes the grade asks for
  (conversion/allotment amounts from a cumulative sum to this filing's count x price; "issue and allotment of N"
  approvals from `allotment` to `approval`; the issuer vetoes; and the feed-dedupe twins that shift when a folded
  amount changes), but they are ungraded on fresh4/fresh3, so the 25% line is breached rather than hidden.
* **Tests**: `test_t242_r7_raise_step_amount_shapes` (green shoe, premium vs total, CCD conversion, allotted-only),
  `test_t242_r7_not_the_listed_company_as_issuer` (six quoted shapes) and `test_t242_r7_raise_stage_shapes`
  (recommendation, AGM notice, concluded press release, approval-subject-to-EGM); 121 passed.
* **Deliberate ceilings.** The title shortcut trusts the subject line's count (a filing that allots less than its
  subject says would store the subject count); a split-adjusted conversion with no printed total uses the printed
  unit price (66,00,000 shares x Rs 297, the papers' own figure); the NCD instrument is matched on "non-convertible"
  and `NCD` words only, so a notice that names a bare "debenture" for one resolution and a QIP for another can still
  take the debenture amount; the issuer veto is read on two pages, so a filing that narrates an acquisition deeper
  than page 2 can still be read as its own raise.

## 4. Model fallback

Only a classified **order win** whose printed value the script could not fill is sent, once, to `hy4-flash-free`
on OpenCode Go (`reasoning_effort: "none"`, strict JSON, the first two pages only); the reply is cached in
`.tmp/t231/model_cache.json` so a rerun never re-spends the free quota. The same printed check applies, against the
first two pages; a value whose unit word is not in the quoted text is `unverified`; a value not on those pages is
`quarantined`; `known_at` still comes from `doc`. A 429 honours `Retry-After` (cap 900 s) and retries. The stage-C
run made 0 new requests (the cache held the earlier replies) and produced 14 verified order-win rows.

## 5. Duplicates, amendments, parent scope

* **B2 same order filed twice**: same symbol, kind `order_win`, value within 0.5% (annual base or `value_total`
  counts), same customer when both printed (an initialism of the full name counts, round 4; or an exactly equal
  value when one is missing), filing dates within 7 days: the
  earlier `known_at` row stands; the later document goes to `amend` (28 links this run: 24 same-order twins, 4 real
  addenda/corrigenda).
* **B3 amendment links** are on `event.amends` (PREMEXPLN 163 -> 155).
* `entity_scope='parent'` when the title/first 1500 characters name a parent/ultimate-holding-company release.
  These are kept and `unverified` (3 rows this run, all NAVKARCORP store press releases from JSW Infrastructure).
  **Brief drift:** the store's parent label lives on linked transcripts ("parent company call: JSW Infrastructure
  Limited"), not on announcements; c08's JSW material is a transcript/deck, so the parent detection on announcements
  is text-based only.
* The exchange feed files the same document twice (BSE + NSE): same symbol, filing date, kind and value/capacity is
  kept once. This is feed dedupe, not cross-filing dedupe: a raise approval and its later allotment remain two dated
  rows, as the brief asks.
* **B4 same raise step filed twice** (round 5, `_fold_same_raise`): same symbol, `fund_raise`, an amount within 0.5%
  (or the same printed share count), filing dates within 10 days: the repeat (a press release, an errata, a second
  letter) names the kept step in `amend` and is dropped. Two letters filed the same day about one step keep the more
  advanced stage; a notice and a later stage on a later day are never folded (an approval and its allotment stay two
  rows). 36 folds on the 25 fresh4 stores, 9 on the 20 fresh3 stores.

## 6. Run (91 stores, 21 Nov 2026)

```bash
python -m reality_engine.research.filing_events --workers 4 \
  --out .tmp/t231/events.db --report-file .tmp/t231/report_a.md
python -m reality_engine.research.filing_events --no-model --limit 200 --stores c01 c08 \
  --out .tmp/t231/smoke.db --report-file .tmp/t231/smoke.md
# T-233 scoped re-read: only the selected filings, merged into a copy of the baseline
python -m reality_engine.research.filing_events --out .tmp/t231/events_fix.db \
  --baseline D:/RealityEngine/t231/events.db --only .tmp/sel.json --workers 4
python -m reality_engine.scripts.regress events --db .tmp/t231/events_fix.db \
  --baseline D:/RealityEngine/t231/events.db
# T-242 round 4 on the unseen sets (stores read from the universe build, read-only)
T228_STORE_ROOT=C:/RealityEngine/tg_build/full394 python -m reality_engine.research.filing_events \
  --stores $(cat C:/RealityEngine/t242/fresh4_stores.txt) --workers 4 \
  --out .tmp/events_round4_fresh4.db --cache .tmp/events_cache.db \
  --report-file .tmp/events_round4_fresh4_report.md      # and the same with fresh3_stores.txt
# T-242 round 7: the 40 fresh5 stores, cache copied from C:/RealityEngine/t242/fresh5/events_cache.db
T228_STORE_ROOT=C:/RealityEngine/tg_build/full394 python -m reality_engine.research.filing_events \
  --stores $(cat C:/RealityEngine/t242/fresh5_stores.txt) --workers 4 \
  --out .tmp/events_r7_fresh5.db --cache .tmp/events_cache.db --report-file .tmp/report_r7_fresh5.md
```

T-233's golden set (`reality_engine/tests/golden/events.jsonl`, 69 rows from
`t231_wolf_read_{a,b}.md`) keys events by content, not `event_id`: Wolf read the stage-A DB (440 events) and the
current file is stage C (604), so 69 unique rows matched content, 11 were ambiguous and 20 rows changed or vanished
between stages. Details: `docs/FIX_LOOP.md`.

| measure | stage A | stage B | stage C |
|---|---|---|---|
| stores / announcements read | 91 / 11,330 | 91 / 11,330 | 91 / 11,330 |
| classified filings | 467 | 670 | 691 |
| events written | 440 | 603 | 604 (61 symbols, 2024-04-25 .. 2026-11-13) |
| filings per class | order 289 / capex 21 / capacity 8 / fund 149 | order 397 / amendment 5 / capex 46 / capacity 16 / fund 218 | order 390 / amendment 6 / capex 33 / capacity 16 / fund 255 |
| events by status / method | verified 246 (script 233, model 13), unverified 194, quarantined 0 | verified 340 (script 321, model 19), unverified 263, quarantined 0 | verified 439 (script 425, model 14), unverified 165, quarantined 0 |
| need model / share | 81 / 17.3% | 125 / 18.7% | 106 / 15.3% (stop > 30%) |
| amend links | 3 | 28 | 36 (31 recap twins + 5 addenda) |
| raise ids / primaries | - | - | 157 / 157 |
| verified companies / month-ends | order 29/31; capex 7/8; fund 9/12 | order 34/32; capex 16/13; fund 24/22 | order 34/31; capex 9/12; fund 42/32 |

Stage B detail: `.tmp/t231/report_b.md` (before/after, every cited id, the seed-9 recall, verified order_win
companies per month-end 2024-06..2026-10, 30 random verified events seed 17). Stage A report:
`.tmp/t231/report_a.md` (30 random verified seed 7).

Recall (30 random order/contract/allot titled filings, seed 9, pool 914): 10 should-be events, all 10 present
(8 on the sampled `doc_key`, BIL/AFCOM on the twin document that B2 kept and linked); all 20 negatives stayed out
(postal ballots, ESOP allotments, approvals, monitoring reports). Stage A recall was 3 of 5.

## 7. Checks

```bash
python -m pytest -q reality_engine/tests/test_filing_events.py   # 121 passed (T-242 round 7)
python plugins/code-tools/ct.py typecheck reality_engine/research/filing_events.py \
  reality_engine/tests/test_filing_events.py                     # 2 pre-existing sys.stdout.reconfigure errors
```

## 8. Limitations / not built

* Cross-filing folding is order-only for the duplicated filing (B2/C2/C4) and raise-step-only for a raise (B4); a
  capex approval and its later press release with a slightly different value can still be two rows (IRMENERGY
  337.04 cr on 6/7 Aug 2026 is the known case).
* A raise that prints a total and a 25%/75% component is no longer summed (round 5: YASHHV 504 stores the printed
  total 151 cr, was 242 cr). Round 7 sends a balance/instalment clause ("remaining 75% amount", "balance subscription
  amount", "i.e. 75% of the issue price") to the shares x price read, so the RUSHIL 75% receipts (fresh5 #17, #19,
  #21, #41) are no longer the amount; a filing that prints ONLY a balance receipt, with no count and no total, has no
  size and falls to the model. The same pass reads a plain 2x share print as the same raise.
* Recall is counted at event level: a repeat filed under two doc_keys can leave the sampled doc_key without a row
  while the event exists on the twin (SAKAR, KROSS in the seed-21 sample).
* The model sees only the first two pages; an amount printed deeper is not recovered (it stays `unverified`).
* `capacity_commissioned` is intentionally narrow: planned expansions are `other` (or a capex approval when a
  quantified board approval exists).
* A multi-line "Broad consideration" cell with several per-order values is read as the first value by
  `order_wins`; round 4 corrects it when the title prints the aggregate and the body prints that total (the
  headline-aggregate case), otherwise the first item stays.
* Parent/subsidiary dedupe across stores is not built; `entity_scope` labels the scope instead: `parent` for the 3
  parent-labelled capex rows, `subsidiary` for a named subsidiary's order (round 6, name in `detail`), else
  `company`. The scope test is document-level, not sentence-level (a subsidiary's order keeps its verified status;
  see 3e for its ceiling).
* `tasks/STATE.md` carries the current T-242 line (round 7's structural rules and the fresh5/fresh4/fresh3 counts); the
  controller re-runs the loader on the merged round-7 DBs.

## Wolf's independent reads (21 Nov 2026)
Stage A (seed 311): verified 40 = 28 right / 8 minor / 4 wrong; recall 3/5. Stage B (seed 411): verified 50 = 37 / 9 / 4
(order_win 29 / 5 / 1). Every cited defect checked in stage C (fund-raise raise_id/primary, 120-day press-release fold,
buyer/exploring/completion vetoes, restated dates, field hygiene). Detail `D:/RealityEngine/t231/wolf_read_{a,b}.md`;
final DB `D:/RealityEngine/t231/events.db` (604 events, 439 verified). Factor use: one row per raise_id
(raise_primary=1); order_win only with order_kind new order; companies with a verified order win in the trailing 12
months: median 25 of 91 over 2025-06..2026-10.
