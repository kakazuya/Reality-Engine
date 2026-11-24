# T-231: filing-level events from exchange announcements

Built 21 Nov 2026 by a dsh worker for ticket T-231 (Wolf 21 Nov, from Shivam's plan step 2; reviewer Wolf).
Stage A built the table; **Stage B** (after Wolf's read A: 37 right / 9 minor / 4 wrong of 50 verified) fixed the
nine named defect classes; **Stage C** (read B) adds the fund-raise stage/`raise_id`, the 120-day press-release
recap fold, the buyer/exploring/completion/borrowing vetoes, restatement dating, field hygiene and the multi-order
split. The factor study needs dated, quantified corporate events, one row per filing; T-228's generic claim
extractor over calls and annual reports restated facts across documents and stored parent-company facts under a
subsidiary.

Code `reality_engine/research/filing_events.py`; tests `reality_engine/tests/test_filing_events.py` (85 tests, no
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
* **Fund raise** is the size, issue price, share count and instrument. A bundled outcome with several raises sums
  the distinct printed sizes (computed -> `unverified`); a size printed only as shares x price is computed. Stage B
  fixed the wrong-item case (SHREEPUSHK: the 350 cr capex is capex, the raise is 7,36,196 warrants x 407.5 = 30 cr,
  computed; SPMLINFRA: preferential 5.75 + warrants 177.43 + shares 7.16 = 190.34 cr, computed).
* Every figure carries the exact printed span (`value_text`), its page (0 = the exchange headline) and the sentence
  (`quote`). `_locate` matches the number against the page's own money/capacity spans, accepting the printed
  full-rupee form and a "crore"-suffixed full figure (`Rs. 7,40,06,30,000 Crore` -> 740.063 cr).

Status (T-242 round 3, 24 Nov 2026): `verified` = every field printed, scope company **and the row's kind is in
`VERIFIED_KINDS`** (`frozenset({"order_win"})`; `_gate_status`); `unverified` = a computed figure, an amount the
script could not fill, a parent-scope row, or a kind that has not passed its own fresh strict 60-row grade (detail
`kind_not_gated: <kind> awaits its own 60-row grade`); `quarantined` = the value is not on the page. A kind joins
`VERIFIED_KINDS` only after its own fresh 60-row grade, so `fund_raise`, `capex_approval`,
`capacity_commissioned` and `order_amendment` rows are never verified until then. Run 24 Nov 2026 on the 20 fresh3
stores: 251 events, 0 quarantined, no non-order row verified.

## 3b. Stage C rules

* **C1 fund-raise stage.** `raise_stage` is `intimation`, `approval`, `allotment`, `listing` or `completion`, read
  from the title/opening. `_assign_raise_ids` groups rows into one raise by symbol, instrument family, size within
  5% (a same-day 2x print is the same raise) and 365 days; `raise_id` is the same across stages and exactly one row
  per id has `raise_primary=1` (allotment > completion > approval > listing > intimation; earliest on a tie).
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
python -m pytest -q reality_engine/tests/test_filing_events.py   # 85 passed (T-242 round 4)
python plugins/code-tools/ct.py typecheck reality_engine/research/filing_events.py \
  reality_engine/tests/test_filing_events.py                     # 2 pre-existing sys.stdout.reconfigure errors
```

## 8. Limitations / not built

* Cross-filing folding is order-only for the duplicated filing (B2/C2); a capex approval and its later press release
  with a slightly different value can still be two rows (IRMENERGY 337.04 cr on 6/7 Aug 2026 is the known case).
* A filing that prints a total and a component amount (YASHHV 504: total 151 cr, equity tranche 91 cr) is summed to
  242 cr; the `raise_id` is right and only the primary row is used, but the size is high. The same pass reads a
  plain 2x share print as the same raise.
* Recall is counted at event level: a repeat filed under two doc_keys can leave the sampled doc_key without a row
  while the event exists on the twin (SAKAR, KROSS in the seed-21 sample).
* The model sees only the first two pages; an amount printed deeper is not recovered (it stays `unverified`).
* `capacity_commissioned` is intentionally narrow: planned expansions are `other` (or a capex approval when a
  quantified board approval exists).
* A multi-line "Broad consideration" cell with several per-order values is read as the first value by
  `order_wins`; round 4 corrects it when the title prints the aggregate and the body prints that total (the
  headline-aggregate case), otherwise the first item stays.
* Parent/subsidiary dedupe across stores is not built (no announcement in the 91 carried a parent label); the 3
  parent-labelled capex rows are kept with `entity_scope='parent'`.
* `tasks/STATE.md` is not edited: the brief forbids it; the controller should add the T-231 status/accept line.

## Wolf's independent reads (21 Nov 2026)
Stage A (seed 311): verified 40 = 28 right / 8 minor / 4 wrong; recall 3/5. Stage B (seed 411): verified 50 = 37 / 9 / 4
(order_win 29 / 5 / 1). Every cited defect checked in stage C (fund-raise raise_id/primary, 120-day press-release fold,
buyer/exploring/completion vetoes, restated dates, field hygiene). Detail `D:/RealityEngine/t231/wolf_read_{a,b}.md`;
final DB `D:/RealityEngine/t231/events.db` (604 events, 439 verified). Factor use: one row per raise_id
(raise_primary=1); order_win only with order_kind new order; companies with a verified order win in the trailing 12
months: median 25 of 91 over 2025-06..2026-10.
