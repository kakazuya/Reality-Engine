# Reader review 2 — Beam vs MiniMax under prompt v3

**Reviewer:** DeepSeek (Hotline job 5; reports to Claude)
**Date:** 2026-10-20, 04:02–04:12 IST
**Scope:** **all 4** `minimax-m3.1-flash-free~high` v3 docs (`run_at >= 2026-10-20T04:00`, `status='ok'`) and **4 random** `beam-free` v3 docs (`checks_json.prompt='v3'`, `status='ok'`); 8 items per doc = 64 items, each checked against the source PDF transcript for meaning.
**Verdict:** MiniMax **scale up — yes**, with two operational conditions (§9); Beam **keep** as primary, lint fixes only. Material errors in this tranche: **0/32 MiniMax, 0/32 Beam**. The rates are *not* a paired before/after with review 1 — see §8, which matters more than the headline.

---

## 1. What was reviewed, and how

**Source of items:** `reality_engine/data/concall_facts.db`, `cc_docs` / `cc_items` (opened `mode=ro`).
**Source of transcript:** `corporate_documents.local_file_path` in `reality_engine/data/equity_intelligence.db` where `id = doc_id` (read-only), text extracted with pymupdf. All 8 PDFs existed (12–25 pages).
**Sampling:** Python `random.Random(20261021)`, same algorithm as review 1: per doc, one random item from each of `guidance`, `order_book`, `capex`, `key_numbers` that existed, then random items from the remaining lists until 8, then shuffle. The seed differs from review 1 (20261020) so this is an independent draw; the method is identical. Every doc had at least 8 items, so the full 8/doc was checked.
**Priority coverage:** 12 guidance, 4 order_book, 7 capex, 26 key_numbers, 15 other (capacity/projects, demand, margin, balance sheet, risks, analyst pushback).
**Quote check:** all **64/64** quotes are verbatim substrings of the pymupdf text after case/whitespace normalisation (the only misses on a case-sensitive first pass were sentence-initial capitals, not wording).

**Materiality rule (same as review 1).** An item is **wrong (material)** when its own structured fields (`value`/`amount`, `metric`/`purpose`, `period`/`as_of`, `basis`, `direction`) would lead a user to a different fact than the transcript. Label/field defects that are visible in `item_json`, or that do not change the numeric fact, are listed separately as **other defects** and are not counted material.

**Sample frame.** `concall_facts.db` was live. The MiniMax v3 corpus was complete at **4 docs** for the whole review. Beam v3 grew from **89 docs at draw** to **111 by 04:07**, so the Beam sample is 4 of a moving 111-doc set — 3.6% of docs, 32 of 8,296 extracted items (0.4%). Counts below are as observed at 04:02–04:09 IST.

### Sample

| Reader | doc_id | Symbol | Period discussed | Items extracted / rows | Items checked | Seconds |
|---|---|---:|---|---:|---:|---:|
| MiniMax | 48352 | KAJARIACER | Dec-2025 fraud update; FY25/FY26 | 45 / 43 | 8 | 115.9 |
| MiniMax | 89596 | TRITONV | Q2 & H1 FY26 + FY28-30 targets | 95 / 93 | 8 | 191.8 |
| MiniMax | 61804 | NH | Q2 & H1 FY26 | 84 / 77 | 8 | 198.5 |
| MiniMax | 45580 | IZMO | Q2 & H1 FY26 | 91 / 87 | 8 | 203.6 |
| Beam | 58510 | MOLDTECH | Q2 FY26 | 72 / 70 | 8 | 55.5 |
| Beam | 91769 | V2RETAIL | Q2 & H1 FY26 | 141 / 134 | 8 | 47.5 |
| Beam | 39301 | HINDALCO | Q2 FY26 | 148 / 143 | 8 | 58.4 |
| Beam | 31717 | FREDUN | Q2 & H1 FY26 | 86 / 86 | 8 | 72.8 |

Two MiniMax docs (48352 KAJARIACER, 89596 TRITONV) were in review 1's v2 sample; two (61804 NH, 45580 IZMO) are new. One Beam doc (58510 MOLDTECH) was in review 1's v2 sample.

---

## 2. Result summary

| Reader | Docs | Items | Correct | Wrong (material) | Material rate | Wrong by type | Other defects (sampled) | 95% CI (exact) |
|---|---:|---:|---:|---:|---:|---|---:|---|
| **MiniMax** | 4 | 32 | 32 | **0** | **0.0%** | none | 9 | 0–10.9% |
| **Beam** | 4 | 32 | 32 | **0** | **0.0%** | none | 6 | 0–10.9% |

**What this does and does not say.** Zero material errors in 64 items is a clean result on precision, but a 32-item sample with zero errors still has an upper 95% confidence limit of **10.9%** — above both v2 point estimates (4.2% Beam, 6.3% MiniMax). Fisher exact tests on v2-vs-v3 rates are not significant (Beam p≈0.51, MiniMax p≈0.49). The stronger evidence is **item-level**: the three exact failure classes review 1 found (JV/subsidiary total as own capex, parent/global figure as own guidance, analyst number as company fact) do not recur unlabelled anywhere in the 64 items, and in the three docs read under both prompts the KAJARIACER and TRITONV defects are fixed while MOLDTECH's duplicate is not (§8).

---

## 3. Wrong items (material) — none

There is no item in the 64 whose structured fields lead to a different fact than the transcript. The three closest calls, each of which is why they are *not* counted:

| # | doc / item | Why it looks wrong | Why it is not material |
|---|---|---|---|
| 1 | **48352 KAJARIACER `capex#0`** — INR 120 cr, "since May 2023" | The amount is the **step-down subsidiary Kerovit Global's** historical total capex, not Kajaria's own capex. Review 1 flagged the same row (v2) for a start-date period and for putting the subsidiary total in the capex list, though its `purpose` already named Kerovit. | The purpose now reads *"Kerovit Global Pvt. Ltd. historical total capex for the new sanitary plant; not prospective company capex guidance"*, the period is now "since May 2023", and the same fact is separately in `key_numbers#7` with the entity named. This is the treatment review 1 §6.1/§6.10 asked for; residual risk is only that there is no `entity` field for programmatic aggregation. |
| 2 | **61804 NH `guidance#5`** — INR 30–50 cr | Analyst-origin number (not management's), and `period` says "by Q2 of next year", not "annual". | Exact label `(confirmed analyst's figure)`; `question_gist` carries *"INR 30 to 50 crore **annual** revenue impact"*; quote is management's non-bare confirmation. This is the P3 path working. The annual basis not being in `period` is a field defect (§4, MM-D5), not a misattribution. |
| 3 | **31717 FREDUN `guidance#6`** — INR 90 cr PAT FY29 | Analyst-origin number; value not in the quote. | Exact label, `question_gist` carries 90, quote *"We would definitely be on track to achieve those numbers as for now"* is management confirming, not a bare yes. Correct P3 handling. |

The other two analyst-origin numbers found in the 8-doc scan behave the same way (48352 `key_numbers#0`, labelled; 48352 `key_numbers#8`, labelled but with a bare quote — §4/§7). **No unlabelled analyst number appears in `key_numbers`, `order_book`, `guidance` or `capex` in any of the 64 sampled items or in the full numeric-list scan of the 8 docs**, and that scan found only three numeric items whose value is absent from the quote — all three labelled and all three with the number in the carrier (§7).

---

## 4. MiniMax — other defects (9 in the sample, 2 more in the full-item scan)

| # | doc_id / symbol | Item | Issue | v3 rule |
|---:|---|---|---|---|
| MM-D1 | 48352 KAJARIACER | `capex#0` — INR 120 cr | Subsidiary historical capex sits in the company `capex` list. Explicitly labelled "not prospective company capex guidance", but there is no entity column, so `SUM(amount)` by doc still returns it as Kajaria capex. Duplicated in `key_numbers#7`. | 2 / 6.10 |
| MM-D2 | 89596 TRITONV | `key_numbers#2` (and #0–#10, #15; `margin_and_cost_commentary#0`, #1, #6) | `metric` says "Standalone/Consolidated …" but `basis` is blank on **15 items**. v3 rule 5 says set it. The metric carries the word, so the fact is not misleading. | 5 / 6.9 |
| MM-D3 | 89596 TRITONV | `key_numbers#4` — normalized EBITDA YoY change | `value` is the spelled-out ASR string **"hundred and Fifteen-Sixteen"** with `unit: basis points`; it means 115–116 bps and is not normalised to a number. The gate passes it automatically (P1, no numeric token). | 9 / 6.4 |
| MM-D4 | 89596 TRITONV | `order_book#3` — first Middle East defence order | No value; `as_of` = **Q3 FY26** (the call-date quarter) while the second order is "should come in Q4". `period` is a call-date quarter, not an order-book/commitment date. | 8 / 6.5 |
| MM-D5 | 61804 NH | `guidance#5` — INR 30–50 cr CGHS uplift | The **annual** basis lives only in `question_gist`; `unit` is "crore" and `period` is the alignment date ("by Q2 of next year"). A fields-only reader cannot tell 30–50 cr/year from 30–50 cr in total. | 8 / 6.5 |
| MM-D6 | 61804 NH | `key_numbers#13` — GBP 190m | "Practice Plus acquisition **transaction cost**" is the acquisition consideration/EV (GBP 40m equity + 150m debt), while `key_numbers#16` uses "transaction cost" for the **5% expense rate**. Two different meanings under one label. | 10 / 6.7 |
| MM-D7 | 61804 NH | `key_numbers#5` — non-packaged CGHS benefit 12% | Management said *"we would not see any benefit **beyond** 12%"*; the item records 12% as the benefit. A ceiling is stored as a point, with no "up to". | 11 |
| MM-D8 | 45580 IZMO | `capex#1` — INR 130–140 cr | `period` "FY '26 and FY '27" is not in the quote; it is inferred from the 10–12-month execution comment. The amount is the machinery component of a 150–200 cr project (disclosed in `purpose`). | 8 / 6.5 |
| MM-D9 | 45580 IZMO | `guidance#9` — izmoMicro INR 200 cr | `basis: segment`, but izmoMicro is a **subsidiary**, not a segment; v3 rule 5 allows `segment` only when the call says the figure is for a segment. | 5 / 6.9 |
| MM-D10 *(scan)* | 48352 KAJARIACER | `key_numbers#8` — INR 8.5 cr CWIP | Analyst number, exact label and `question_gist` present, but the quote is *"Yes, yes, this number is correct."* — a bare confirmation that passes the gate's 6-token rule by exactly one token and contains no number. Correctly labelled, but label-dependent. | 3 / 6.2 |
| MM-D11 *(scan)* | 45580 IZMO | `guidance#0` — FY26 revenue growth 20–30% | `direction: unclear` for a range that is reiterated in the same call (*"We are sticking to the same number"*); v3 rule 4 would say `maintained` (or `lowered`, since 25–30% became 20–30%). | 4 / 6.3 |

**MM-D2 is the one systematic lapse.** It is the exact 6.9 fix review 1 wrote for Beam's ESTER rows ("if `metric` says standalone/consolidated, set `basis` to that value"). MiniMax applied it to `guidance#0` (basis standalone) but not to the 15 numeric rows.

---

## 5. Beam — other defects (6 in the sample, 2 more in the full-item scan)

| # | doc_id / symbol | Item | Issue | v3 rule |
|---:|---|---|---|---|
| B-D1 | 91769 V2RETAIL | `key_numbers#26` — 275 stores, `period: current quarter` | The call is the Q2 FY26 call; "current quarter" is **Q3 FY26 to date** ("so far in the current quarter … as of today"). Q2/H1 end was **259** stores (`key_numbers#24`). No `as_of`. A period filter on the Q2 doc attaches 275 to Q2. Not counted material because the quote says "as of today" and the same list carries 259/H1, so the timing is recoverable. | 8 / 6.5 |
| B-D2 | 91769 V2RETAIL | `capex#0` — INR 350-odd cr, "next year" | The amount is **capex plus inventory investment** for 150 stores, not pure capex. Disclosed in `purpose`, but a capex aggregation overstates capex by the inventory component, which is not split out. | 2 / 7 |
| B-D3 | 58510 MOLDTECH | `order_book#2` — $600,000 | Duplicate of `key_numbers#10` (same value, quote, period). **All three** MOLDTECH `order_book` items are duplicates of `key_numbers#11/#9/#10` (total/civil/MES work on hand); none is an order book. Unchanged from review 1's v2 finding. | 10 / schema |
| B-D4 | 39301 HINDALCO | `guidance#2` — USD 300m cost reduction, FY28 exit | This is **Novelis's** 3-year cost programme, not the India business; `metric` says only "structural cost reduction" and only `basis: segment` hints at it. Novelis is consolidated, so it is Hindalco group guidance, but the entity is not named. | 2 / 6.1 |
| B-D5 | 31717 FREDUN | `key_numbers#17` — 1,700 products | `unit` is empty. "1,700" with no unit is only interpretable from `metric`; v3 rule 9 requires a token (`products`). | 9 / 6.4 |
| B-D6 | 31717 FREDUN | `capex#1` — INR 5–7 cr, `period: later` | Second tranche of a 9–12 cr Wagr.ai investment (`capex#0` holds the 4–5 cr first tranche); "later" is not a period, and a reader summing the two tranches gets 9–12 cr, not 5–7. `purpose` discloses the platform. | 8 / 6.5 |
| B-D7 *(scan)* | 39301 HINDALCO | `key_numbers#32` — India copper demand 420 Kt, `period: quarter` | "Quarter" rather than Q2 FY26; same for `#33` (11% growth). | 8 |
| B-D8 *(scan)* | 39301 HINDALCO | `key_numbers#43` — FY27 hedge price 2,800 | Omits the 10% hedge coverage that the same sentence gives; `key_numbers#42` carries it separately, so the pair is recoverable. | 10 |

**B-D3 is structural and not new.** It is the same MOLDTECH row review 1 flagged under v2; v3 did not change it, and the whole MOLDTECH `order_book` list is duplicated work-on-hand. The `order_book`-duplicates-`key_numbers` pattern is **cross-reader** (see §6), so it is a prompt/schema issue rather than a Beam defect.

---

## 6. v3 rule scorecard (what the prompt was written to fix)

| v3 rule | MiniMax | Beam | Evidence |
|---|---|---|---|
| **2 / 6.1 scope** (JV/subsidiary/parent) | **Pass.** Every scope-bearing capex/guidance item is entity-labelled: Kerovit Global (subsidiary, "not company capex"), Tritonvalves Future Tech and Climatech (subsidiaries, named), izmoMicro (subsidiary, named). 0 undisclosed. | **Pass.** Bay Minette USD 5bn explicitly "Novelis; total project cost, not company annual capex"; Beryl labelled "(subsidiary)". 1 residual: HINDALCO USD 300m Novelis programme unnamed (B-D4). | Item text in `purpose`/`metric`. |
| **3 / 6.2 analyst-only numbers** | **Pass in substance.** 3 analyst-origin numeric items in 4 docs (KAJARIACER #0, #8; NH guidance#5). All name the analyst's figure; #8 and NH#5 carry the exact `(confirmed analyst's figure)` label, #0 an extended "(confirmed analyst's figure; approximate range stated)" and passes on the number being in its own quote. 0 unlabelled. | **Pass.** 1 analyst-origin numeric item (FREDUN guidance#6, PAT 90 cr), exact label + carrier. 0 unlabelled. | Mechanical scan of all 8 docs: only 3 numeric values absent from their quote, all 3 labelled with the number in the carrier (§7). |
| **4 / 6.3 direction of reiterated targets** | **Pass.** 7 `maintained`: TRITONV 1000 cr, NH 3000 cr capex, IZMO 50-50 mix / 200 cr / >30% / photonics-equal / FY27 margin improvement. 0 cases of `new` on "reiterated / maintain / on track / stick / committed". 1 weak `unclear` (MM-D11). | **Pass.** 3 `maintained` (V2RETAIL pre-Ind AS margin, HINDALCO 300m, FREDUN PAT 90). 0 `new` on explicit reiteration. 2 `raised` (V2RETAIL 100→130 stores; HINDALCO 75→100→125m savings) are correct. | 56 guidance items across the 8 docs; direction distribution MiniMax 7 maintained / 16 new / 3 unclear / 1 lowered; Beam 3 maintained / 20 new / 2 raised / 4 unclear. |
| **5 / 6.9 basis** | **Partial fail.** 15 TRITONV rows say "Standalone/Consolidated" in `metric` but leave `basis` blank (MM-D2). | **Partial.** 5 HINDALCO rows with "consolidated" in `metric` leave `basis` blank (field-only, metric carries it). | Counted by query, not by eye. |
| **7 / 6.8 capex needs an amount** | **Pass.** No `amount: null` capex in the 4 docs (v2 had BASF and TRITONV null-amount rows). | **Pass.** No null-amount capex. | Full capex list. |
| **8 / 6.5 period/as_of** | **2 defects:** TRITONV order book `as_of` = call-date quarter (MM-D4); NH annual basis missing from `period` (MM-D5). | **3 defects:** V2RETAIL "current quarter" (B-D1); FREDUN "later" (B-D6); HINDALCO "quarter" (B-D7). | — |
| **9 / 6.4 unit** | **1 defect:** TRITONV spelled-out bps value (MM-D3). | **1 defect:** FREDUN blank unit (B-D5). | Otherwise units are tokens (`%`, `bps`, `INR crores`, `USD million`, `Kt`, `x`, `stores`). |
| **10 / 6.7 inconsistent figures** | **Pass where seen.** TRITONV 600 vs 650 cr imports flagged "inconsistent in call"; KAJARIACER 19.9/19.7 range carried. | **Pass where seen.** MOLDTECH 4.2–4.3 civil vs >4.5 total flagged "inconsistent in call"; HINDALCO 20.5 vs 5.45 carried as separate years; V2RETAIL carries both 259 (H1) and 275 (current) rather than silently picking one. | — |

**Cross-reader defects that are not a model choice:**
- `order_book` duplicates `key_numbers`: MOLDTECH 3/3, TRITONV order_book#0-2 = key_numbers#16-18, IZMO order_book#0 = key_numbers#21. Both readers do this. A user querying `order_book` gets backlog figures already in `key_numbers`; a user summing both double-counts.
- `basis` blank despite the metric saying standalone/consolidated: both readers (15 MiniMax rows, 5 Beam rows).
- These are prompt/schema lints, not evidence for one reader over the other.

---

## 7. Gate behaviour and coverage (the main operational finding)

`cc_docs.checks_json` does **not** carry the new gate counts uniformly. As observed at 04:09:

| Model | v3 `ok` docs | Docs with `bad_value_in_quote` key | Items in gated docs | Gate drops | `number_not_in_quote` | `bare_confirmation` | `analyst_number_missing` | `quote_empty` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| beam-free | 111 | **52 (47%)** | 5,312 | 75 (1.41%) | 51 | 24 | 0 | 0 |
| minimax | 4 | **1 (25%)** | 91 | 1 (1.10%) | 1 | 0 | 0 | 0 |

- **The gate went live on only part of the run.** 59 of 111 Beam v3 docs and 3 of 4 MiniMax v3 docs have `"prompt": "v3"` but no gate keys at all. The gated and ungated docs are **interleaved in run order** (e.g. Beam 80258 at 04:01:23 ungated, 42381 at 04:07:36 gated; HINDALCO 04:05:32 ungated, 84441 at 04:06:21 gated). Same `key_name` (`OPENCODE_GO_API_KEY`), so this looks like two loader code paths — an old process and a new one — writing concurrently, not a time switch. Until that is settled, no per-reader gate pass-rate can be quoted for the v3 tranche.
- **Where it did run, the shape is exactly the spec.** `bad_value_in_quote` = `number_not_in_quote` + `bare_confirmation` + `analyst_number_missing` + `quote_empty` (Beam 75 = 51+24+0+0; MiniMax 1 = 1). No `analyst_number_missing` and no `quote_empty` in any gated doc: no item used the label without the number in the carrier.
- **The 6-token bare-confirmation rule has a hole.** 48352 `key_numbers#8` is a pure confirmation — *"Yes, yes, this number is correct."* — six tokens, so P3 passes and the gate would keep it. It is correctly labelled, so this is a spec weakness, not a bad row; but "at least six tokens" is not a sufficient test for "management said something substantive". A verb-count or a "contains a content word other than this/that/number/correct" test would close it.
- **Drop accounting matches the rows.** Extracted `items` minus `bad_quote`/`bad_number`/gate drops equals the rows stored: KAJARIACER 45−2=43, TRITONV 95−2=93, NH 84−7=77, IZMO 91−4=87, MOLDTECH 72−2=70, V2RETAIL 141−7=134, HINDALCO 148−5=143, FREDUN 86−0=86.

**Consequence for the scale-up decision:** MiniMax's content passed, but the gate did not cover 3 of its 4 v3 docs. Scaling MiniMax now means scaling the reader without the safety net on most rows.

---

## 8. v2 vs v3 — error rates, and why the comparison is weaker than it looks

| Tranche | Reader | Docs | Items | Material wrong | Rate | 95% CI (exact) |
|---|---|---:|---:|---:|---:|---|
| v2 (review 1, 03:26–03:52) | Beam | 6 | 48 | 2 | 4.2% | 0.5–14.3% |
| v2 | MiniMax | 4 | 32 | 2 | 6.3% | 0.8–20.8% |
| **v3 (this review)** | **Beam** | 4 | 32 | **0** | **0.0%** | 0–10.9% |
| **v3** | **MiniMax** | 4 | 32 | **0** | **0.0%** | 0–10.9% |

**The samples are not paired, so the rate change is confounded by which docs were drawn.** The two v2 MiniMax material errors were in **14752 BASF** (global parent capex in India guidance) and **80180 SINGERIND** (analyst's Rs 2.3 cr income tax). Neither was re-read under v3 — the v3 MiniMax corpus is only 4 docs, and two of them (KAJARIACER, TRITONV) had **zero** material errors under v2. So "6.3% → 0%" is a different sample, not a measured fix of those two rows. The same applies to Beam: the v2 errors were ESTER (1,600 cr JV capex) and GRWRHITECH (direction `new`); only MOLDTECH overlaps, and MOLDTECH had no material error under v2. "4.2% → 0%" is likewise a different sample.

What *is* item-level evidence, in the three docs read under both prompts:

| Doc | v2 finding | v3 state |
|---|---|---|
| **48352 KAJARIACER** | `capex#0` period was a start date ("from around May 2023"), subsidiary scope only in `purpose`; `balance_sheet#0` quote did not carry the INR 20 cr facts (other defects). | Period fixed to "since May 2023"; purpose now says Kerovit Global, historical, "not prospective company capex guidance"; the analyst's INR 20 cr and INR 8.5 cr CWIP numbers now carry the exact label and `question_gist`. The v2 defects are fixed; one new field defect (bare quote on #8). |
| **89596 TRITONV** | `capex#1` had `amount: null`; `balance_sheet#3` "Future Tech" was called an invented entity. | Null-amount capex gone (12 cr, "since March"). **Review 1's "invented entity" finding was wrong**: the same call names *"Tritonvalves Future Tech Private Limited"* as the metals subsidiary. The v3 row's entity name is correct; review 1 §4.2 should be corrected. |
| **58510 MOLDTECH** | `order_book#2` duplicated the MES work-on-hand key number and could read as total order book. | Unchanged, and now it is clear the whole MOLDTECH `order_book` list is duplicated work-on-hand (`order_book#0/#1/#2` = `key_numbers#11/#9/#10`). v3 did not fix this class. |

Net: the v2 defect classes that v3 targeted (scope label, analyst label, reiterated-target direction, capex amount, unit tokens) are **absent or labelled** in this tranche; the classes v3 did **not** target (order-book duplication, basis when the metric already says it, period vocabulary like "later"/"current quarter") are still present in both readers. That is the honest reading, and it is more useful than a 0% headline.

**Speed (for scaling):** MiniMax v3 averaged **177 s/doc** (116–204 s) vs Beam **56 s/doc** (35–91 s) — 3.2× slower, still inside the 300 s rule and free. The earlier cull of MiniMax (decisions.md:65) was for xhigh/max at 245–268 s; `~high` is materially faster and no longer trips the rule.

---

## 9. Verdicts

### MiniMax — **scale up: yes**, with two conditions

The content condition from review 1 is met **as intended**, not literally:
- **Analyst-origin numbers:** 3 found by the scan in the 4 docs, all identifying the analyst's figure; #8 and NH#5 carry the exact `(confirmed analyst's figure)` label and a `question_gist`, #0 an extended label and passes because its number is in its own quote. **Zero unlabelled** analyst numbers in `key_numbers`/`order_book`/`guidance`/`capex` in 32 sampled items and in the full 124-item numeric-list scan. The literal "zero analyst-origin numbers" is not met (3 are stored), but that is exactly what v3 rule 3 permits and what review 1 §6.2 specified.
- **Parent/subsidiary figures as own capex/guidance:** **zero undisclosed.** Every subsidiary/JV figure in the 4 docs names the entity (Kerovit Global, Tritonvalves Future Tech, Climatech, izmoMicro); the Kerovit capex row says explicitly that it is not a company capex claim. The one residual (KAJARIACER's INR 120 cr subsidiary total in the company capex list) is labelled "not prospective company capex guidance"; it is a disclosed historical fact.

**Conditions (operational, not quality):**
1. **Confirm the gate is running on the MiniMax worker for every doc before scaling.** Only 1 of 4 v3 MiniMax docs carries gate counts (IZMO, 1 gate drop). The other 3 ran through the ungated path. If MiniMax is scaled while the old path is still live, most rows will bypass the safety net.
2. **Close the two field lapses in the same change:** the 15 TRITONV `basis` blanks (6.9) and the bare-confirmation quote on KAJARIACER `key_numbers#8`. Neither is material; both are cheap.

**Recommended, not required:** re-read **14752 BASF** and **80180 SINGERIND** under v3 as the regression test. They are the exact rows v2 failed on, and they are the only direct test of whether the two v2 failures are fixed rather than merely absent from the new sample.

### Beam — **keep** (primary reader), lint fixes only

- **0/32 material**, 64/64 quotes verbatim, no analyst misattribution, no *undisclosed* scope figure presented as the company's own, direction `maintained` where the call reiterates.
- Remaining defects are lint-level: `order_book` duplicates `key_numbers` (structural, cross-reader), a capex amount that includes inventory, three period labels ("current quarter", "later", "quarter"), one blank unit, and the unnamed Novelis programme. None changes a numeric fact when the item is read whole.
- No reason to switch readers. Beam is 3.2× faster and has fewer of these field lints (5 basis blanks vs MiniMax's 15; 6 other defects vs 9), but both readers share the order-book/basis classes.

**If one reader: Beam. If two: Beam primary; MiniMax as a second lane after conditions 1–2.** MiniMax's quality is now close enough that throughput, not correctness, is the reason to add it.

---

## 10. What this sample does not show

- **The two v2 failure docs were not re-read.** BASF and SINGERIND are the direct test of whether the v2 scope/attribution failures are fixed. They are absent from the v3 MiniMax corpus (only 4 docs exist).
- **Statistical power.** 32 items per reader; zero errors still allows a rate up to 10.9% at the 95% level. The 0% is not proof of <4.2%.
- **Recall/completeness.** 8 items per doc, not every item. A reader can be faithful on the sample and still miss the key fact. This review measures precision/meaning, not recall. Example: IZMO `demand_commentary#4` correctly records the tariff outlook but omits the 10–15% growth guidance stated two sentences later; that is a recall gap, not a wrong item.
- **Lists not sampled:** `management_tone`, `investor_takeaway`, `participants`; detailed `analyst_pushback` answer quality (only 2 sampled).
- **The live corpus.** Beam v3 grew 89→111 docs during the review; docs read after the sample are not covered. MiniMax's 4 docs were the whole v3 set.
- **Gate coverage over time.** The 52/111 and 1/4 counts are a snapshot at 04:09; the ungated path was still writing. If Claude re-runs the check later, the coverage numbers will change.
- **Dropped items.** The gate drops rows before insert and does not store them; I cannot tell whether a dropped row was actually correct or a false positive.
- **PDF/ASR edge cases.** pymupdf text; hyphenation and ASR garble can make a true quote look absent. All 64 sampled quotes matched after normalisation; no fabrication was found.
- **Economic importance.** A faithful item can still be useless (e.g. KAJARIACER "fraud accelerated in the last 4–5 months" as a `key_number`). I did not rank investment materiality.

---

## 11. Reproduction

- Sample: `reality_engine/data/hotline/_review_tmp2/sample.json` (seed 20261021; 8 docs; 8 items each, all fields).
- Transcripts: `.../_review_tmp2/txt/<doc_id>_<symbol>.txt` (pymupdf, one per doc).
- Context windows: `.../ctx_<doc_id>.txt` (700 chars before / 900 after each quote, with item fields and `item_json` extras).
- Checks used: value-token-vs-quote scan (all items, 8 docs), guidance-direction scan, scope-marker scan, gate-coverage query, quote-verbatim check (64/64).
- DB reads only: SQLite URI `mode=ro` on `concall_facts.db` and `equity_intelligence.db`; no writes, no status changes, no job control. The running Beam/MiniMax jobs were not touched.

*Prepared 2026-10-20 04:12 IST. The source database was live; Beam v3 counts are as observed at 04:02–04:09 IST.*
