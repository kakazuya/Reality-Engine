# Reader review 1 — Beam vs MiniMax on concall facts

**Reviewer:** DeepSeek (Hotline job 2; reports to Claude)  
**Date:** 2026-10-20, 03:26–03:52 IST  
**Scope:** 6 `beam-free` docs + 4 `minimax-m3.1-flash-free~high` docs, all `status='ok'`; 8 random items per doc (80 items) checked against the source PDF transcript for meaning.  
**Verdict:** Beam **keep with fix** (primary reader); MiniMax **keep with fix, conditional secondary** — gate the numeric lists and re-test before scaling.

---

## 1. What was reviewed, and how

**Source of items:** `reality_engine/data/concall_facts.db`, tables `cc_docs` and `cc_items` (opened read-only).  
**Source of transcript:** `corporate_documents.local_file_path` in `reality_engine/data/equity_intelligence.db` where `id = doc_id` (opened read-only), text extracted with `python` + `pymupdf` (10/10 PDFs existed; pages 12–21 each).  
**Sampling:** Python `random.Random(20261020)`; 6 Beam and 4 MiniMax `ok` docs. Per doc, one random item from each of `guidance`, `order_book`, `capex`, `key_numbers` that existed, then random items from the remaining lists until 8, then shuffled. This gives priority coverage without ignoring the other lists. All 10 docs had at least 8 items, so the full 8/doc was checked (80 items).  
**Priority coverage:** 12 guidance, 6 order_book, 6 capex, 29 key_numbers, 27 other (capacity, demand, margin, balance sheet, risks, analyst pushback, one-offs).

**Sample frame.** The database was live while I read it. The sample was drawn from the then-current `ok` set; a count immediately before the draw gave **93 Beam / 13 MiniMax**. Counts moved during the review (73/12 a minute earlier, **230 Beam / 54 MiniMax by 03:40**), so a job is still writing. At 03:40 the 10 sampled docs were still `ok`, with unchanged item counts. This review is therefore a sample of the early tranche, not of the full current corpus.

**Materiality rule.** An item is counted **wrong (material)** when its own structured fields (`value`, `metric`, `period`/`as_of`, `basis`, `direction`) would lead a user to a different fact than the transcript. Label/field defects that are visible in `item_json` or do not change the numeric fact are listed separately as **other defects** and are not counted in the material rate. This distinction is stated because some scope issues are visible in `item_json` (e.g., KAJARIACER's `purpose` names Kerovit Global) and would be caught by a careful reader. The BASF global-guidance item is still counted material despite the visible "Global" label, because it sits in BASF India's `guidance` list and a per-symbol query returns it as India guidance.

### Sample

| Reader | doc_id | Symbol | Period discussed | Items in doc | Items checked |
|---|---|---:|---|---:|---:|
| Beam | 55983 | MARKSANS | Q2 FY'26 (H1 also) | 87 | 8 |
| Beam | 118455 | KHAZANCHI | Q2 & H1 FY'26 | 88 | 8 |
| Beam | 84441 | SURAKSHA | Q2 & H1 FY26 | 95 | 8 |
| Beam | 36351 | GRWRHITECH | Q2 & H1 FY26 | 97 | 8 |
| Beam | 29635 | ESTER | Q2 FY'26 | 130 | 8 |
| Beam | 58510 | MOLDTECH | Q2 FY26 | 91 | 8 |
| MiniMax | 14752 | BASF | Q2 & H1 FY26 | 90 | 8 |
| MiniMax | 48352 | KAJARIACER | FY26 / FY25 + fraud update | 53 | 8 |
| MiniMax | 80180 | SINGERIND | Q2 & H1 FY25-26 | 88 | 8 |
| MiniMax | 89596 | TRITONV | Q2 & H1 FY26 + outlook | 88 | 8 |

---

## 2. Result summary

| Reader | Docs | Items checked | Correct | Wrong (material) | Material error rate | Wrong by error type | Other defects |
|---|---:|---:|---:|---:|---:|---|---:|
| **Beam** | 6 | 48 | 46 | **2** | **4.2%** | scope/entity 1; direction 1 | 5 |
| **MiniMax** | 4 | 32 | 30 | **2** | **6.3%** | attribution 1; scope/entity 1 | 7 |

Both readers passed the mechanical quote/number checks that produced the database: every quote I checked is verbatim in the extracted text, and every number is in the transcript. The failures are **meaning** failures, not fabrication: wrong entity, wrong period, unsupported direction, and analyst words/numbers treated as management facts.

The single largest misstatement is Beam's: **INR 1,600 crore of JV project capex entered as Ester Industries' capex**, when management explicitly says the project is not on Ester's books. The highest-risk single item is MiniMax's **Rs 2.3 crore income tax**, which exists only in an analyst's question and has no analyst-origin label. MiniMax's Rs 200 crore order-book item is a different case: its `inflow_or_pipeline` says "management confirmed the analyst's figure", so it is counted as a field defect, not a misattribution.

---

## 3. Beam — wrong items

**Beam result**

| Items checked | Correct | Wrong (material) | Wrong by error type | Other defects |
|---:|---:|---:|---|---:|
| 48 | 46 | 2 | scope/entity 1; direction 1 | 5 |

### 3.1 Material errors (2/48)

| # | doc_id / symbol | Item | Quote | Why it is wrong | Error type |
|---:|---|---|---|---|---|
| B1 | **29635 ESTER** | `capex#0` — amount INR 1,600 crores, period "ELITe project (completion by December 2027)" | "That is a project of about INR1,600 crores capex." | The INR 1,600 crore is the **total capex of the 50:50 Ester Loop Infinite Technologies (ELITe) JV**, not Ester Industries' capex. Management says: *"It is not going to be on the books of Ester. It is going to be a separate company called Ester Loop Infinite Technologies Private Limited. So any debt to complete this new project is going to be on the books of ELITe."* Ester's own share is about **INR 250–270 crore of equity** (*"if Ester has to put about INR250 crores, let us say, INR250 crores, INR270 crores"*). The item's `purpose` says only "ELITe chemical recycling project" and `funding` gives the JV's equity/debt split; it does not say the project is off Ester's books or that the amount is the JV total. A reader aggregating Ester capex overstates it by roughly **INR 1,330–1,350 crore**. | Scope / entity |
| B2 | **36351 GRWRHITECH** | `guidance#2` — "Garware Application Studios", value 300-plus studios, period by end FY26, direction **new** | "We are well on track to cross 300-plus studios by the end of FY '26" | "Well on track" refers to an existing target; it is not a first-time figure. Prompt v2 rule 3 says `maintained` only when the call refers to an earlier guidance figure, and a first-time figure is `new`; here the call signals continuation, so the supported label is **`maintained`** (or `unclear` if no prior figure is identifiable), **not `new`**. The value/period themselves are correct. | Direction |

**Evidence note — ESTER (B1).** The transcript has three separate statements that together settle the scope:
- *"It is not going to be on the books of Ester. It is going to be a separate company called Ester Loop Infinite Technologies Private Limited. So any debt to complete this new project is going to be on the books of ELITe."*
- *"So that is a project of about INR1,600 crores capex. It is going to be implemented by Ester Loop Infinite Technologies, which is a 50-50 joint venture company between Ester and Loop. And it's going to be funded by about INR500 crores to INR600 crores of equity and the balance INR1,000 crores to INR1,100 crores of debt."*
- *"So out of INR1,600 crores, INR500 crores to INR600 crores will be equity, which will be equally divided between Loop and Ester. So if Ester has to put about INR250 crores, let us say, INR250 crores, INR270 crores..."*

This is not a quote problem: the quote is verbatim. It is a **scope** problem: the item stores the JV total where the schema means the company's capex. The fix is to put Ester's share in `amount` (or keep the project total but mark it explicitly "JV total — not company capex" in `purpose`/`metric`), and to name the JV in the item.

### 3.2 Other Beam defects (not counted material)

| doc_id / symbol | Item | Issue |
|---|---|---|
| 55983 MARKSANS | `guidance#0` — UK revenue, value "double", unit "UK revenues" | **Unit is not a unit.** "UK revenues" is a noun phrase; for a doubling, `unit` should be `x` (value 2) or `%` (value +100). The metric/value/direction are right. |
| 29635 ESTER | `key_numbers#44` — "Parent dollar loan", value "around INR10 million", unit "INR million" | **Unit/ambiguity.** The metric says *dollar* loan, but the unit is INR. The transcript says *"we also have a small amount of dollar loan in the parent entity ... which is around INR10 million."* A USD 10m loan and an INR 10m loan differ by ~88x. Prompt rule 4 says write `unclear` when the transcript is ambiguous; the item silently picks INR. It copies the speaker, so this is a transcript ambiguity, not a fabrication — but a downstream user cannot tell which currency is meant. |
| 29635 ESTER | `key_numbers#16` and `key_numbers#22` | **Basis left blank** even though the metrics say "Consolidated capacity utilization" and "Standalone EBITDA" and the transcript says "on a consolidated basis" / "stand-alone financial performance". `basis` should be `consolidated` / `standalone`. The metric carries the word, so the fact is not misleading, but the field is empty. |
| 36351 GRWRHITECH | `key_numbers#21` — export share 76%, Q2 FY26 | **Conflicting figure not flagged.** Prepared remarks say *"Exports continue to be the cornerstone of our growth, contributing 77% of total revenues this quarter"*; the Q&A says *"around 76% is the export and 24% is the domestic."* The item records only 76% and does not say "inconsistent in call" (prompt rule 8). The 1pp difference is small; the omission is the defect. |
| 58510 MOLDTECH | `order_book#2` — $600,000, Q2 FY26 | **Duplicate / label.** This is the same MES work-on-hand figure as `key_numbers#11`; `inflow_or_pipeline` says "MES work on hand", but the order_book item has no metric, so it can read as total order book. The call gives civil work on hand of >$4.5m separately (*"the current work on hand, it's more than $4.5 million"*), so a reader can mistake $600k for the whole order book. |

Beam's 2 material errors are in different docs and different error classes; there is no repeated Beam-specific failure in the 48 items. The repeated cross-reader issues are scope (JV/global/subsidiary) and direction for reiterated targets.

---

## 4. MiniMax — wrong items

**MiniMax result**

| Items checked | Correct | Wrong (material) | Wrong by error type | Other defects |
|---:|---:|---:|---|---:|
| 32 | 30 | 2 | attribution 1; scope/entity 1 | 7 |

### 4.1 Material errors (2/32)

| # | doc_id / symbol | Item | Quote | Why it is wrong | Error type |
|---:|---|---|---|---|---|
| M1 | **80180 SINGERIND** | `key_numbers#20` — "Income tax paid", Rs 2.3 crores, H1 FY25-26 | "the advance tax is always paid based on the projection of the full year. To avoid tax liability, interest liabilities, that's why we have paid a higher tax to be in compliance." | **The Rs 2.3 crore is the analyst's number, not management's.** The analyst says: *"as per cash flow statement, income tax paid is Rs. 2.3 crores, whereas PBT for each one of these fiscals is just Rs. 1.98 crores."* Management's answer explains why advance tax is high; it **never states or confirms 2.3**. The value does not appear in the item's quote (my value-in-quote check flags it). Prompt v2 rule 5 requires a "confirmed analyst's figure" label when management only says yes; there is no such label, and management did not even say yes to the number. The H1 period is also inferred, not stated in the quote. | Attribution |
| M2 | **14752 BASF** | `guidance#0` — "Global capital expenditure relative to depreciation", value "below depreciation", period "up until 2028" | "there has been a clear signal that Capex given this large cap ex investment that we did in China, that Capex will come below depreciation on a global level up until 2028." | **This is the global parent's capex outlook, not BASF India's guidance.** The call is BASF India; management explicitly says *"on a global level"* and refers to the large China investment. The item is labelled "Global" in `metric`, which reduces the risk, but it is stored in **BASF India's `guidance` list** with no entity field; a query by `doc_id` or symbol returns it as BASF India guidance. Prompt v2 rule 6 says a guidance item must be the company's own outlook, not an industry figure; a parent/global figure is the same class of scope error. The capex duplicate (`capex#0`, amount null) is listed under other defects. | Scope / entity |

**Evidence note — SINGERIND (M1).** The income-tax item is the clean failure: a number spoken by the analyst is stored as a company fact, management never repeats it, and there is no "confirmed analyst's figure" label. The same doc's `order_book#1` (Rs 200 crores) is **not** counted material: its `inflow_or_pipeline` says "management confirmed the analyst's figure and the June 2027 completion timeline" and notes the Rs 202 crore inconsistency. That is the rule-5 handling. Its remaining problems — the bare "Yes, Laksh, absolutely." quote and the `as_of` Q2 FY25-26 label — are field-quality defects, listed in §4.2. The same doc's `key_numbers#25` does the order correctly: metric "PMY order amount, confirmed analyst's figure", period "through June 2027". So the model can apply the rule; it failed on the income tax item, not on every analyst number.

**Why M2 is counted material despite the "Global" label.** The number is not false; the entity is wrong for a per-company guidance table. The item's `metric` says Global, but `cc_docs.symbol = BASF` and the row sits in BASF's guidance list. A downstream consumer that filters by doc/symbol — the normal access path — will read it as BASF India guidance. The fix is either omit it from `guidance` (put it in a group/parent context field that does not exist) or add an explicit `entity`/`scope` field so it cannot be confused with India guidance.

### 4.2 Other MiniMax defects (not counted material)

| doc_id / symbol | Item | Issue |
|---|---|---|
| 14752 BASF | `capex#0` — amount null, period "up until 2028" | Same global-parent statement as M2; **no amount** and no company-entity label. A capex item with `amount: null` is not a capex fact; the statement belongs in `guidance` (qualitative) or `capacity_and_projects`, not `capex`. |
| 48352 KAJARIACER | `capex#0` — approximately INR 120 crores, period "from around May 2023" | **Subsidiary total capex with a start date as the period.** The analyst asks *"what is the quantum of the total capex which was done in this subsidiary?"*; management answers *"this company was started capex in last year, around May 2023. Then entire year capex was going on and total capex was approximately INR120 crores."* `purpose` correctly says "New sanitary ware plant at Kerovit Global", so the scope is disclosed; but `period` is a start date, not a reporting period, and the amount is cumulative subsidiary capex, not Kajaria's capex. A reader aggregating Kajaria capex can double-count or mis-date it. |
| 80180 SINGERIND | `order_book#1` — Rs 200 crores, `as_of` Q2 FY25-26 | **Field quality, not misattribution.** The value is the analyst's, but `inflow_or_pipeline` explicitly says "management confirmed the analyst's figure and the June 2027 completion timeline", which is the rule-5 handling. The defects are the bare "Yes, Laksh, absolutely." quote (the value is not in the quote) and `as_of` Q2 FY25-26 without a separate order date; the June 2027 completion is only in `inflow_or_pipeline`. A value-in-quote gate would flag the quote; a careful reader is not misled about the source. |
| 80180 SINGERIND | `guidance#4` — facility setup 8–12 months, `basis: segment` | `basis: segment` is **unsupported**. The call says the facility is for the new-generation ZigZag category, but it does not say "segment" as the basis of the figure. Prompt rule 2 says `standalone`/`consolidated` only if the word is said, otherwise `unknown`; the same discipline should apply to `segment`. |
| 89596 TRITONV | `capex#1` — amount null, period Q3–Q4 FY26 | **No amount.** The quote is only *"Some of the CapEx actually we have shown here also, we are going to be spending for further automation of our lines."* There is no money figure and no purpose beyond "automation". This is a forward-looking capex statement, not a capex fact; it should be in `capacity_and_projects` or `guidance` until an amount is given. |
| 89596 TRITONV | `balance_sheet_and_cash#3` — "allocate two to three crores to **Future Tech**" | **Invented entity name.** The transcript says *"possibly take allocate two to three crores for future tech the metal business"* — "future tech" is a phrase about future technology for the metal business, not a named company "Future Tech". The amount and the use of cash are otherwise right. |
| 48352 KAJARIACER | `balance_sheet_and_cash#0` — "Approximately INR20 crores ... self-created vendor ... remainder written off against Kerovit Global's P&L" | **Quote support is thin.** The quote is only about exceptional-expenditure treatment: *"I think it should be shown as an exceptional thing ... 99% it will be shown as an exceptional expenditure."* The INR 20 crore/self-created vendor/recoveries facts are elsewhere in the call and are supported there, but this quote does not carry them. The statement's "written off against Kerovit Global's P&L" is an inference from "exceptional expenditure", not a stated write-off. |

MiniMax's non-material defects cluster in three areas: **entity/scope** (parent, subsidiary), **field discipline** (`basis`, `amount`, `as_of`), and **not-stated details** ("Future Tech", P&L write-off). That is why the verdict is not just a rate comparison.

---

## 5. Verdicts

### Beam — **keep with fix**

- **48 items, 46 faithful, 2 material errors (4.2%)**, in two different docs and two different classes.
- No analyst-attribution error in the sample. Quotes, numbers, and periods were otherwise right; basis labels were right except the two ESTER key numbers noted in §3.2. The `analyst_pushback` items correctly quote management, and the guidance items correctly separate guidance from history except for the `new`/`maintained` slip.
- **Keep Beam as the primary reader.** The fixes are narrow: JV/subsidiary capex scope; direction for reiterated targets; unit-field lint. A 1,600 crore scope error is serious enough that the fix should be in prompt v3, not left to the next review.
- If Beam is already the chosen reader (per `decisions.md`, 2026-10-20 02:18), this review supports that choice: it is the cleaner of the two on attribution and has the lower material error rate.

### MiniMax — **keep with fix (conditional secondary)**

- **32 items, 30 faithful, 2 material errors (6.3%)**: one **attribution** (Rs 2.3 crore income tax from the analyst's question, no label) and one **scope** (BASF global parent capex in the India guidance list).
- The income-tax item is the critical defect: it is exactly what prompt v2 rule 5 was written to prevent, and the value does not appear in the quote. The Rs 200 crore order-book item is **not** counted material because it labels the analyst confirmation in `inflow_or_pipeline`; its bare quote and `as_of` are field defects. In the same doc, `key_numbers#25` handles the order correctly — so this is inconsistent application, not inability.
- The sample is small (4 docs, 32 items), so 6.3% is an estimate, not a precise rate. MiniMax is not stopped on this sample, but it is **not cleared as a primary reader** and should not be scaled until the value-in-quote gate and a fresh 4-doc blind test pass.
- **Conditions before scaling:** (1) prompt v3 with the rules in §6; (2) the value-in-quote gate in §6.6 enforced for MiniMax rows, not just DeepSeek rows; (3) a fresh 4-doc sample with zero analyst-origin numbers in `key_numbers`/`order_book`/`guidance` and zero parent/subsidiary figures presented as the company's own capex/guidance. If Claude wants MiniMax only for throughput, run it on the qualitative lists (`demand_commentary`, `margin_and_cost_commentary`, `risks_and_headwinds`, `pricing_and_competition`) behind the gate, not on the numeric lists.

**If the choice is one reader: Beam.** If two, Beam primary and MiniMax secondary behind the gate.

---

## 6. Prompt v3 fixes (keyed to observed errors)

These are additions/edits to `reality_engine/data/concall_pilot/prompt_v2.md`. 6.1–6.6 are must-fix; 6.7–6.10 are field lint.

### 6.1 Entity/scope block for capex and guidance

> Before writing a `capex` or `guidance` item, name the entity whose money/outlook it is: the listed company (standalone/consolidated), a subsidiary, or a JV/associate. If the figure is a JV/project total or a parent/global figure, do not put it in the company's `capex`/`guidance` list. Either omit it, or put the company's own share in the amount and say "JV total, not company capex" / "global parent, not India" in `purpose` or `metric`.

Why: Beam B1 (ELITe JV), MiniMax M2 (BASF global), MiniMax KAJARIACER `capex#0` (Kerovit subsidiary). This is the most repeated cross-reader class.

### 6.2 Analyst-origin numbers

> Never put a number in `key_numbers`, `order_book`, `guidance`, or `capex` if the number appears only in an analyst's question. If management confirms it, record it only with the metric suffix "(confirmed analyst's figure)", put the analyst's number and question in `question_gist` (or `inflow_or_pipeline` for `order_book`), set `period`/`as_of` to the commitment date, and quote management's confirmation. If management does not repeat the number, do not add it to `key_numbers` at all.

Why: MiniMax M1 (Rs 2.3 crore income tax). The Rs 200 crore order-book item is the same class but labels the confirmation in `inflow_or_pipeline`; the value-in-quote gate catches its bare quote without counting it as a misattribution.

### 6.3 Direction for reiterated targets

> If management says "well on track", "maintain", "reiterate", "stick to", "remain", "on course" about a target, use `maintained` (or `unclear` if no prior figure is identifiable), never `new`. `new` is only for a figure/outlook first introduced in this call.

Why: Beam B2 (300+ studios). The same wording appears in many calls; this is a cheap fix.

### 6.4 Unit field

> `unit` must be a unit token from the transcript: `%`, `bps`, `INR crore`, `INR million`, `USD million`, `tonnes`, `metric tons`, `x`, etc. Never put a noun phrase ("UK revenues") in `unit`; put the noun in `metric`. For a multiple, use `x` and value `2`, or value `double` and unit `x`. If the transcript's unit is internally inconsistent (e.g., "dollar loan ... INR10 million"), use `unit: unclear` and say why in `statement`/`period`; do not silently pick one.

Why: Beam MARKSANS `guidance#0`, ESTER `key_numbers#44`.

### 6.5 Period/as_of

> `period`/`as_of` must be a reporting period or measurement date, not a start date or the call date. For cumulative capex, use "since May 2023" or the fiscal year; for orders, use the order-book date and put the delivery/completion date in `inflow_or_pipeline`.

Why: MiniMax `order_book#1` (bare `as_of` Q2 FY25-26; completion only in `inflow_or_pipeline`), KAJARIACER `capex#0` ("from around May 2023").

### 6.6 Value-in-quote gate (prompt + mechanical)

> For `key_numbers`, `capex`, `order_book`, and numeric `guidance`, the number in `value` must appear in `quote`, or the item must carry the exact "(confirmed analyst's figure)" label and the number must appear in `question_gist` (or `inflow_or_pipeline` for `order_book`). A bare "Yes"/"No" quote cannot support a numeric value.

This is both a prompt rule and a check. In the sample, the two MiniMax material attribution errors are exactly the two numeric items whose value does not appear in the quote; Beam had none. `cc_item_checks.value_in_quote` is **NULL for Beam and MiniMax rows** (it appears to have been populated for the older DeepSeek pass only), so the existing mechanical gate did not cover these readers. Populate/ enforce it for every reader before scaling.

### 6.7 Inconsistent figures

> If the call states two different figures for the same thing, record both and mark "inconsistent in call" in `metric` or `statement`, as rule 8 already says. Do not silently pick one.

Why: Beam GRWR 76% vs 77%; MiniMax order book 200 vs 202 (MiniMax did note the inconsistency in `inflow_or_pipeline`; Beam did not note 76/77).

### 6.8 Capex amount required

> If no amount is stated, do not create a `capex` item; put the statement in `capacity_and_projects` or `guidance` (qualitative). A capex item with `amount: null` is not a fact.

Why: MiniMax BASF `capex#0`, TRITONV `capex#1`.

### 6.9 Basis when the metric already says standalone/consolidated

> If the metric says standalone/consolidated, set `basis` to that value; do not leave it blank. If the transcript does not say the word, `unknown`.

Why: Beam ESTER `key_numbers#16`/`#22`; MiniMax SINGERIND `guidance#4` (basis `segment` unsupported).

### 6.10 Name the subsidiary/JV

> Name the subsidiary/JV in `purpose`/`metric`; put the company's share in `amount`; put the project total in `purpose` as "project total, not company capex".

Why: Beam B1, MiniMax KAJARIACER `capex#0`.

---

## 7. What this sample does not show

- **Recall/completeness.** I checked 8 items per doc, not every item. A reader can be faithful on the sampled 8 and still miss the most important fact in the call. This review measures precision/meaning, not recall. The earlier reader comparison (`decisions.md`, 2026-10-19 22:01) measured recall separately (Beam 92.9%, Zen MiniMax 94.1% vs DeepSeek).
- **Statistical confidence.** 48 and 32 items are small. The 6.3% and 4.2% are sample estimates; do not treat them as population rates. The keep/gate decision is a risk judgment, not a significance test.
- **The full current corpus.** The DB grew from 93/13 `ok` docs at draw to 230/54 by 03:40. Docs read after the sample are not covered. The running job was not touched.
- **Lists not sampled.** `management_tone`, `investor_takeaway`, `participants`, and the detailed `analyst_pushback` answer quality were not systematically checked. The sample included a few `analyst_pushback` items and they were correctly attributed to management, but that is not a full check.
- **Economic importance.** An item can be faithful and still useless (e.g., "impressive order book (not quantified)"; a capex item with no amount). I flagged the empty items, but I did not rank materiality for an investment thesis.
- **PDF extraction edge cases.** I used pymupdf text extraction; hyphenated line breaks and garbled ASR can make a verbatim quote look absent from my extracted text. I resolved these by searching the raw transcript; no quote in the sample was found to be fabricated.
- **The database's own checks.** I did not modify `cc_docs`, `cc_items`, `cc_item_checks`, or any queue/status. The wrong rows are still in the DB; quarantining or re-reading them is Claude's call.

---

## 8. Reproduction

- Sample: `reality_engine/data/hotline/_review_tmp/sample.json` (seed 20261020; 10 docs; 8 items each with all fields).
- Transcripts: `reality_engine/data/hotline/_review_tmp/txt/<doc_id>_<symbol>.txt` (pymupdf, one file per doc).
- Item dump: `reality_engine/data/hotline/_review_tmp/items.txt`; JSON-field dump: `.../items_json.txt`.
- Context windows: `.../ctx_<doc_id>.txt` (800 chars before/after each quote, with transcript line numbers).
- Checks: `.../valquote.py` (value-in-quote), `.../scan_all.py` (all current rows), `.../numcheck.py` (numbers in `item_json` vs transcript).
- DB reads only: `sqlite3` URI `mode=ro` for both databases; no writes, no status changes, no job control.

---

*Prepared 2026-10-20 03:52 IST. The source databases were live; counts in §1 are as observed at 03:26–03:40 IST.*
