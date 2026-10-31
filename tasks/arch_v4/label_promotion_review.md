# Label promotion review — measured frequency, free Beam suggestions

Generated 2026-10-31T00:29:12+00:00 by `python -m reality_engine.query.v4.promote_vocab` from `.tmp/v4_vocab_source_copy.db (byte copy of C:\RE\data\pilot\v4\v4_vocab.db; the mount is read-only)`. Model `beam-free` (free) on OpenCode Go, `reasoning_effort=low`. **This file is a proposal: no label was applied.**

**Status:** for Opus and Shivam to approve. The mapper fix in `build_vocab.py` is code (ratio topics + spelling merge); the promotions below are not. Unlabelled surfaces stay searchable as `other:<raw>`; nothing was deleted.

## 1. Executive summary

- The installed store labels **76.14% of uses** (1,382,374 / 1,815,581) and **62.40% of surface-company pairs** (123,408 / 197,782); 89,960 of 148,652 surfaces (60.52%) carry a label.
- The deterministic mapper fix in this checkout adds **15,241 uses** (0.84 pp) and **739 surface-company pairs** without any model call: ROE/ROCE/ROA/RONW now have declared labels and the `p&l` / `balance sheet` spellings merge onto `financials`.
- The **500 promoted surfaces** in this review add **105,080 uses** (5.79 pp) and **6,287 surface-company pairs** if approved.
- Assuming approval, coverage becomes **82.77% of uses** and **65.95% of surface-company pairs**. The 95% uses target is still **12.23 pp short**; see §9 for what would close it.

## 2. Data limit stated up front

The job mounts only `v4_vocab.db`; the three extraction stores (`concall_facts.db`, `ar_facts.db`, `deck_figures.db`) are not present. The brief asks for the share of occurrences with a value or quote attached. That is an occurrence-weighted source measurement, and it cannot be computed from the stored vocabulary. This review therefore reports the **two verbatim excerpts already stored in `beam_context`** as a sampled proxy: `value 1/2` means one of two excerpts carries a digit; `quote 2/2` means both excerpts are text of at least three words. It is evidence of what the surface is attached to, not a claim about all occurrences. Re-running against the extraction stores would make it exact; the field is marked `sampled` in the proposal JSON.

## 3. The mapper bug: ROE, ROCE and `ROCE %`

**Root cause, measured.** `words_of` normalises `ROE` to the single token `roe`, `ROCE` to `roce`, and `ROCE %` to the same `roce` because `%` becomes the stop token `pct`. `TOKEN_TO_TOPIC` had no entry for any of them, and `PHRASE_TOPICS` had no `return on equity/capital` phrase, so `label_for` returned `("other", "other")`. The bug is not the short length of the token: it is that the declared layer never named the ratio. There were **935 ROE**, **869 ROCE**, **192 `ROCE (%)`**, **190 `RoE%`**, **190 `RoCE%`**, **101 `ROE (%)`** and **77 `RoE`** occurrences in the pilot store, plus `ROA` (339) and `RONW` (32). Beam's pass2 left them `other` because the closed label list did not contain them either.

**Fix.** `build_vocab.TOPICS` now declares `roe`, `roce`, `roa` and `ronw` under `financial_performance`; `PHRASE_TOPICS` adds `return equity -> roe`, `return capital employed -> roce`, `return asset -> roa` and `return worth -> ronw`; and `FOOTNOTE_RATIO` strips a glued footnote digit (`ROCE1`, `ROE2`) before mapping. `return capital` alone is deliberately not a phrase: `capital returns` normalises to the same two tokens and must not become ROCE. `ROCE (Pre-tax) (TTM)` now resolves to `roce` rather than `tax`; `Normalized ROCE (EBITDA basis)` resolves to `roce` because the occurrence-weight rule prefers the rarer token (`roce`) over `ebitda`.

## 4. Spelling merge

`SPELLING_VARIANTS` is applied before punctuation is expanded, so embedded extractor keys merge too: `p&l`, `P&L`, `p_and_l`, `p/l`, `pnl`, `consolidated_p_and_l`, `supplementary_pnl` all normalise to `profit and loss`; `balance_sheet`, `balance-sheet`, `balancesheet` all normalise to `balance sheet`. A statement heading (`p&l`, `balance sheet`) then maps to the existing label `financials` **only when no specific topic rides with it**: `Consolidated P&L – Depreciation` stays `depreciation` and `P&L – EBITDA` stays `ebitda`, while a bare `p&l` or `P&L extract` becomes `financials`. That also fixes the old `profit and loss -> loss` accident. This is a merge of spellings, not a guess: the merged words still go through `label_for`.

| variant family | surfaces | uses | mapped to |
|---|---:|---:|---|
| `p&l / p_and_l / pnl` | 92 | 4,552 | financials (41), ebitda (7), revenue (6) |
| `balance sheet / balance_sheet` | 130 | 5,868 | financials (62), cash (12), roce (5) |

## 5. How the promotion queue was ranked

Every surface that is still unlabelled **after** the deterministic fix is a candidate. Rank score = uses × (1 + ln(1 + documents)) × (1 + ln(1 + companies)); ties break on uses then surface id. The review takes the top 500 by that score, then **adds every lower-ranked surface a master-bank question names**, regardless of frequency (brief item 5). `n_docs` is an exact distinct-document count; `n_isins` is the per-surface distinct-company count stored by the build. Surface-company pairs are the sum of `n_isins`; that is an incidence count, not a de-duplicated company roster (the store does not hold the roster).

## 6. The Beam pass

- **Surfaces sent:** 500 (0 unanswered); **top 500** plus **907 rare but asked kept** (the kept list is not in the Beam queue).
- **Batches:** 13 done, 0 pending; 64,170 tokens in / 23,315 out; median batch 30.5 s; 0 429s.
- **Decisions:** new_label 281, bucket 139, meaningless 63, alias_of 17. `bucket` is never a label and its items keep their own text.
- **Session:** `v4_label_promotion` via `go_session.session_id` (stable across resume); every call is recorded at $0 through `cost_ledger.record_usage`.
- **Agreement:** not asserted. This pass asks once and retries a rejected answer once; unlike VOCAB_PASS2 it does not run a second independent round, so no agreement percentage is claimed. The review is the human check.

## 7. Gate report — uses and company spread

| measured | installed (before) | after mapper fix | after proposals (approved) |
|---|---:|---:|---:|
| labelled uses | 1,382,374 (76.14%) | 1,397,615 (76.98%) | 1,502,695 (82.77%) |
| surface-company pairs | 123,408 (62.40%) | 124,147 (62.77%) | 130,434 (65.95%) |
| labelled surfaces | 89,960 (60.52%) | 90,451 (60.85%) | 90,749 (61.05%) |
| head surfaces labelled (95% of uses) | 43,744 / 62,601 (69.88%) | 43,992 (70.27%) | 44,290 (70.75%) |
| gate vs 95% uses | 18.86 pp short | 18.02 pp short | 12.23 pp short |

Head membership here is the deterministic cumulative-95% cut (62,601 surfaces, sorted by uses then surface id); it reproduces VOCAB_PASS2's 43,744 / 62,601 = 69.88% exactly. The tie inside the 22,782 twice-occurring surfaces is still a tie-break artefact, but the uses figure is not tie-sensitive and is the primary gate.

**New topics this takes:** **233 raw new label ids** from 281 surfaces; mechanical de-duplication (singular/plural and identical definitions) groups them into **214 clusters** (19 slugs merge away), so the final topic count is Opus's semantic merge, not the raw 233. 17 surfaces alias to existing labels; 139 are buckets and 63 are meaningless (neither becomes a label). A stricter reading that sends the BRSR/ESG headings (`environment`, `sustainability`, `energy`, `water`, `waste`, `emissions`, `esg`, ...) to `bucket:section` rather than a topic would remove **23,736 uses** from the after figure.

### 7b. New labels Beam proposes (needs family approval)

| proposed label | definition | surfaces | uses | top surfaces |
|---|---|---:|---:|---|
| `environment` | environmental metrics and disclosures | 3 | 4,972 | environment, environmental, Environment |
| `capital_commitment` | capital commitments and pending contracts | 4 | 2,950 | capital_commitment, capital_commitments, commitment |
| `credit_rating` | credit rating assigned by rating agencies | 4 | 2,878 | credit_rating, credit rating, Credit Rating |
| `fair_value` | fair value measurements | 2 | 2,547 | fair_value, fair value |
| `energy` | energy consumption and efficiency | 2 | 2,529 | energy, Energy |
| `aum` | assets under management | 3 | 2,287 | AUM, Total AUM, AUM (₹ ‘000 Cr) |
| `training` | employee training hours and programs | 2 | 2,273 | training, Training |
| `safety` | safety incidents and practices | 1 | 2,227 | safety |
| `exceptional_items` | exceptional and one-off items | 4 | 2,106 | exceptional_items, Exceptional items, Exceptional Items |
| `derivatives` | derivative instruments and exposures | 1 | 2,043 | derivatives |
| `water` | water consumption and usage | 2 | 1,921 | water, esg_water |
| `hedging` | hedging instruments and coverage | 1 | 1,890 | hedging |
| `waste` | waste generation and disposal | 3 | 1,857 | waste, Waste, esg_waste |
| `fair_value_hierarchy` | fair value hierarchy levels | 2 | 1,816 | fair_value_hierarchy, fair value hierarchy |
| `foreign_exchange` | foreign exchange earnings and exposures | 2 | 1,813 | foreign_exchange, foreign exchange |
| `sustainability` | sustainability and ESG initiatives | 2 | 1,763 | sustainability, Sustainability |
| `compliance` | regulatory and statutory compliance | 2 | 1,579 | compliance, Compliance |
| `caro` | CARO audit reporting matters | 1 | 1,361 | caro |
| `foreign_currency_exposure` | foreign currency exposure | 3 | 1,245 | foreign_currency_exposure, foreign currency exposure, Foreign Currency Exposure |
| `goodwill` | goodwill and intangible assets | 2 | 1,241 | goodwill, Goodwill |
| `emissions` | greenhouse gas emissions | 1 | 1,238 | emissions |
| `esg` | ESG performance and ratings | 2 | 1,199 | esg, ESG |
| `liquidity` | liquidity and funding position | 2 | 1,195 | liquidity, Liquidity |
| `corporate_action` | dividends and corporate actions | 2 | 1,176 | corporate_action, corporate action |
| `macro` | macroeconomic indicators | 1 | 997 | macro |
| `fleet` | fleet and plant network | 1 | 958 | fleet |
| `discontinued_operations` | discontinued operations | 2 | 914 | discontinued_operations, discontinued operations |
| `saleable_area` | area available for sale | 2 | 877 | Saleable Area, Saleable Area (Lakhs Sq. ft. |
| `complaints` | complaints received and resolved | 1 | 873 | complaints |
| `fx_exposure` | foreign currency exposure | 1 | 824 | fx_exposure |
| `exceptional_item` | non-recurring items affecting profit | 2 | 767 | exceptional_item, exceptional item |
| `capital` | capital structure and inputs | 1 | 744 | capital |
| `disputed_statutory_dues` | disputed statutory dues | 1 | 692 | disputed_statutory_dues |
| `derivative` | derivative instruments | 1 | 679 | derivative |
| `capital_structure` | capital structure | 2 | 668 | capital_structure, capital structure |
| `project` | projects and initiatives | 1 | 639 | project |
| `sensitivity` | sensitivity analysis | 1 | 633 | sensitivity |
| `energy_consumption` | energy consumption | 1 | 625 | energy_consumption |
| `human_rights_training` | human rights training | 1 | 599 | human_rights_training |
| `iepf` | investor education and protection fund | 2 | 596 | iepf, IEPF |
| `procurement` | purchasing and sourcing | 1 | 594 | procurement |
| `offsetting` | netting of financial assets and liabilities | 1 | 537 | offsetting |
| `fx_sensitivity` | foreign exchange sensitivity | 1 | 532 | fx_sensitivity |
| `certification` | certifications | 1 | 519 | certification |
| `listing` | stock exchange listings | 1 | 514 | listing |
| `grievances` | grievances and complaints | 1 | 509 | grievances |
| `commitments` | commitments | 1 | 499 | commitments |
| `capital_adequacy_ratio` | capital to risk-weighted assets ratio | 1 | 495 | CRAR (standalone) |
| `human_rights` | human rights | 1 | 494 | human_rights |
| `rnd` | research and development | 1 | 486 | rnd |
| `sensitivity_analysis` | effect of variable changes | 2 | 481 | sensitivity_analysis, sensitivity analysis |
| `agm` | annual general meeting | 2 | 473 | agm, AGM |
| `capital_employed` | total capital used in business | 2 | 472 | Capital Employed, Capital Employed* |
| `assurance` | assurance providers | 1 | 469 | assurance |
| `ghg_emissions` | greenhouse gas emissions | 2 | 460 | ghg_emissions, GHG Emissions |
| `litigation` | litigation matters | 1 | 459 | litigation |
| `buyback` | repurchase of company shares | 1 | 446 | buyback |
| `maturity_analysis` | timing of financial liabilities | 1 | 443 | maturity_analysis |
| `msme` | micro and small enterprises | 1 | 436 | msme |
| `capital_adequacy` | regulatory capital adequacy ratio | 2 | 415 | Total Capital Adequacy Ratio, capital_adequacy |

Full list in `tasks/arch_v4/label_promotion_proposal.json`. The family/parent is **not** assigned here; every new label needs a parent from the nine declared families at approval. Beam only suggests the slug and definition.

### 7c. Aliases to existing labels (proposed, not applied)

| existing label | surfaces | uses | examples |
|---|---:|---:|---|
| `product` | 2 | 455 | LCV, PVC Compounds |
| `segment` | 2 | 445 | Solar, General Insurance |
| `geography` | 2 | 432 | Domestic, markets |
| `debt` | 1 | 246 | ECB |
| `auditor` | 1 | 234 | caro_remarks |
| `liability` | 1 | 212 | guarantees |
| `asset` | 1 | 204 | intangibles |
| `payable` | 1 | 203 | msmed_dues |
| `capacity_utilisation` | 1 | 144 | Occupancy % |
| `jv` | 1 | 121 | joint_operation |
| `csr` | 1 | 106 | community |
| `shareholding` | 1 | 95 | ownership |
| `customer` | 1 | 89 | Consumer |
| `employee` | 1 | 78 | human capital |

These are in `tasks/arch_v4/label_promotion_proposal.json` under `aliases`; no `map` row was changed.

### 7d. Buckets (never labels; items keep their own text)

| bucket | surfaces | uses | examples |
|---|---:|---:|---|
| `signal` | 1 | 39,143 | signal |
| `section` | 39 | 15,806 | operations, operational, industry, corporate |
| `table_header` | 48 | 13,242 | Year, Scrip Code, Area Booked (Lakhs sq ft), Total Inflows (A) |
| `deck_line` | 22 | 8,643 | Area Booked, Value of Area Booked, Saleable Area (Lakhs sq ft), Equivalent Area Constructed* |
| `ratio` | 8 | 6,592 | ratio, operational_metric, ratios, Leverage ratio |
| `market_data` | 7 | 5,713 | market_data, market, macro_indicator, market data |
| `entity` | 13 | 2,815 | NBFC, AHL, Jaipur, RE 100 |
| `unit` | 1 | 95 | per_share |

### 7e. Mechanical near-duplicates among the new labels

233 raw slugs collapse to 214 clusters under singular/plural and identical-definition rules. This is a lower bound on the merge Opus should make; it is not applied. The top groups by uses:

| suggested representative | members | uses |
|---|---|---:|
| `exceptional_items` | `exceptional_item`, `exceptional_items` | 2,873 |
| `derivatives` | `derivative`, `derivatives` | 2,722 |
| `foreign_currency_exposure` | `foreign_currency_exposure`, `forex_exposure`, `fx_exposure` | 2,221 |
| `waste` | `environment_waste`, `waste` | 2,061 |
| `emissions` | `emissions`, `ghg`, `ghg_emissions` | 1,940 |
| `grievances` | `grievance`, `grievances` | 893 |
| `disputed_statutory_dues` | `disputed_dues`, `disputed_statutory_dues` | 889 |
| `actuarial_assumptions` | `actuarial_assumption`, `actuarial_assumptions` | 692 |
| `certification` | `certification`, `certifications` | 664 |
| `capital_adequacy_ratio` | `capital_adequacy_ratio`, `crar` | 651 |
| `award` | `award`, `awards` | 460 |
| `safety_incidents` | `safety_incident`, `safety_incidents` | 451 |
| `struck_off_companies` | `struck_off_companies`, `struck_off_company` | 323 |
| `contract` | `contract`, `contracts` | 292 |
| `investor_grievances` | `investor_grievance`, `investor_grievances` | 271 |
| `claims` | `claim`, `claims` | 208 |
| `legal_proceedings` | `legal_proceeding`, `legal_proceedings` | 151 |

**Worker reading, not a pass.** The 17 aliases, 63 `meaningless` calls and 139 `bucket` calls are the safest part of this file: `signal`, `ratio` and `market_data` are extractor keys, not metrics, and the 17 aliases are ordinary synonyms. I would **not** approve all 233 new labels as-is. The BRSR/ESG headings (`environment`, `sustainability`, `energy`, `water`, `waste`, `emissions`, `esg`) are better as a `section` dimension than as topics, and the audit/reporting keys (`caro`, `iepf`, `agm`, `msme`, `certification`, `assurance`, `listing`, `maturity_analysis`, `offsetting`) read as sections or one-off disclosures. The new labels with a real metric behind them (`credit_rating`, `fair_value`, `aum`, `exceptional_items`, `derivatives`, `hedging`, `foreign_exchange`, `liquidity`, `corporate_action`, `goodwill`, `capital_commitment`) are the first tranche I would approve. The 82.77% after-proposals figure assumes every one of the 233 is approved; a stricter approval gives less. This is an opinion for the reviewers, not a decision, and it is not applied.

## 8. Rare but asked terms stay

No label or surface is deleted by this work. Every label keeps its row and every unlabelled surface stays searchable as `other:<raw>`. The three terms the brief names are still declared labels:

| label | surfaces | uses |
|---|---:|---:|
| `tailwind` | 5 | 7 |
| `monsoon` | 47 | 69 |
| `repo` | 12 | 33 |

In addition, **907** lower-ranked surfaces pass the master-bank token/stem/list test and are kept below the top 500 whatever their frequency. The test is deliberately loose (it matches a word a question uses, not always the thing the question asks for), so the kept list includes entity names and section headings as well as rare metrics. None was promoted or deleted; all remain `other:<raw>` until the review table or a later pass names them.

| asked term in the kept list | surfaces | examples |
|---|---:|---|
| `currency` | 75 | foreign currency sensitivity, currency_sensitivity, Foreign Currency Sensitivity |
| `crude` | 56 | Entered into technical collabo, Manufacturing 1 ton of Beta & , crude_oil_imports |
| `buyback` | 39 | share_buyback, Buyback, share buyback |
| `hedging` | 32 | Hedging, Hedging Instruments, oci_hedging_reserve |
| `forex` | 22 | forex_sensitivity, forex exposure, forex sensitivity |
| `freight` | 12 | PAN INDIA FREIGHT INDEX, East West Dedicated Freight Co, Freight traffic in BTKM |

Largest kept surfaces (evidence only; not in the Beam queue):

| surface | uses | companies | bank match | example question |
|---|---:|---:|---|---|
| `group share of entities` | 122 | 1 | stem | Which companies' results notes mention a related-party loan or advance to a promoter-group |
| `rights_issue` | 96 | 3 | exact | A company announces a rights issue at a discount. Trace it to the share count, then to the |
| `forex exposure` | 96 | 2 | list | Garware: tariff hit, then negative correlation |
| `stock market data` | 96 | 2 | token | On 24 September 2026 the Nifty 50 fell 1.64% but PB Fintech fell 36%. Was this a market mo |
| `LIFE INSURANCE CORPORATION OF INDIA` | 87 | 1 | token | What does Life Insurance Corporation Of India (NSE: LICI) make, and what was its NSE close |
| `T&D:` | 87 | 1 | exact | How many equity shares does Lumax Auto Technologies have, and what is the promoter holding |
| `stock_market` | 80 | 2 | token | On 24 September 2026 the Nifty 50 fell 1.64% but PB Fintech fell 36%. Was this a market mo |
| `foreign currency sensitivity` | 75 | 7 | list | Garware: tariff hit, then negative correlation |
| `Standalone % in consolidated` | 74 | 1 | token | For Reliance and Tata Steel, do the standalone and consolidated filings carry the same aud |
| `construction_contracts` | 74 | 1 | token | Coking coal rises. Steel mills raise HRC, construction cost rises, and highway EPC contrac |
| `Hedging` | 72 | 3 | exact | Garware: tariff hit, then negative correlation |
| `Hedging Instruments` | 72 | 1 | list | Garware: tariff hit, then negative correlation |
| `currency_sensitivity` | 71 | 8 | list | Garware: tariff hit, then negative correlation |
| `forex_sensitivity` | 71 | 7 | list | Garware: tariff hit, then negative correlation |
| `supplier_finance` | 64 | 14 | token | The 16th Finance Commission discontinues revenue-deficit and sector-specific grants to sta |
| ... 892 more in the work store | | | | |

## 9. How far short of 95% this leaves us

After the mapper fix and every proposal in this file, **82.77% of uses** carry a label — **12.23 pp short** of the 95% uses target. That is 222,107 additional uses. By surface count the store is only 61.05% labelled (90,749 / 148,652); the remaining 57,903 surfaces are mostly twice-occurring variants, so a surface-count gate and a uses gate are very different targets.

The next-N curve below is an **upper bound**: it assumes every surface in the rank order can take a label, including the ones Beam calls bucket or meaningless. It is here to size the job, not as a forecast.

| next surfaces labelled (upper bound) | uses coverage | cumulative added |
|---:|---:|---:|
| 500 | 88.65% | +11.67 pp |
| 1,000 | 90.80% | +13.82 pp |
| 2,000 | 92.75% | +15.77 pp |
| 5,000 | 95.01% | +18.03 pp |
| 10,000 | 96.54% | +19.57 pp |
| 20,000 | 97.85% | +20.88 pp |

**What else would close the gap, measured:**

1. **The bucket/section residue cannot be labelled at all.** In this review, 139 surfaces (92,049 uses, 5.07% of the corpus) are buckets or section headings by Beam's reading, and 63 more (14,840 uses) are meaningless alone. The biggest are `signal` (39,143), `market_data` (4,156), `ratio` (4,118), `operations` (2,708), `operational` (1,890). No topic label makes them metrics. Closing the uses gap therefore needs an **extractor fix**: stop emitting the bucket/section key as the metric and keep the item text under it (the `bucket` decision in this review is the spec for that fix), or accept a separate `section` dimension that is not counted as a label. `environment` and `credit_rating` were proposed as topics, not buckets; that choice is part of the review.
2. **The next tranche.** The first 500 add at most 11.67 pp if every one were labelable, but 202 of them are bucket/meaningless and add 0, so the approved set adds 5.79 pp. Surfaces 501-1,000 add at most 2.14 pp (upper bound). After that come longer-tail presentation rows and company/product names; many will be `bucket:deck_line` or `entity`, not a label. Reaching 95% of uses by labelling alone would require labelling the bucket residue too, which would be a false label, not coverage.
3. **The 95%-of-head-surfaces gate** is further away than the uses gate: 43,744 of 62,601 head surfaces carry a label now (69.88%); the mapper fix adds 248 and the promoted labels add 298, leaving 18,311 head surfaces unlabelled. Most are twice-occurring spelling/format variants; the honest route is to promote them by the same Beam pass in batches (the store is resumable) and to stop counting bucket headings as head surfaces.
4. **The label-only ceiling.** The top 500 carry 211,969 uses between them; 106,889 of those (50.4%) are bucket/meaningless. If that mix holds for the 417,966 uses still unlabelled after the mapper fix, only about 207,200 of them are labelable, which caps label-only coverage near **88.4%**. That is an extrapolation, not a measurement, but it is the honest reading: the remaining gap to 95% is an extractor/taxonomy gap, not a shortage of Beam calls.

**The concrete path, in order:** (a) fix the extractors so a bucket key is not emitted as a metric surface (`signal`, `ratio`, `market_data`, `section`, `table_header`, `deck_line`) and keep the item text under it; (b) run the next promotion tranche (501-1,000) through the same resumable pass, then 1,001-2,000; (c) have Opus assign a family to each approved new label, merge the 19 mechanical duplicates and decide whether BRSR/ESG headings are topics or sections; (d) re-measure the gate on the cleaned denominator. Without (a), the label-only ceiling above is the real maximum.

## 10. The review table

One row per promoted surface, ranked by the score. `value` is the sampled value evidence (value-bearing excerpts / excerpts and that share); `quote` is the same for excerpts of at least three words; `bank` is the master-bank match (exact/token/stem/list, `-` for none); `alone` says whether the phrase means anything on its own. `Beam` is a suggestion, not an applied label.

| # | surface | uses | docs | cos | store | value | quote | bank | alone | Beam | definition / Beam reason |
|---:|---|---:|---:|---:|---|---|---|---|---|---|---|
| 1 | `signal` | 39,143 | 427 | 57 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (8) | no: only non-topic words | bucket:signal |  |
| 2 | `ratio` | 4,118 | 206 | 54 | annual_report | 0/2 (0%) | 0/2 (0%) | exact (45) | no: only non-topic words | bucket:ratio |  |
| 3 | `market_data` | 4,156 | 183 | 54 | annual_report | 0/2 (0%) | 2/2 (100%) | token (42) | yes | bucket:market_data |  |
| 4 | `operations` | 2,708 | 248 | 57 | annual_report | 1/2 (50%) | 1/2 (50%) | exact (3) | yes | bucket:section |  |
| 5 | `credit_rating` | 2,291 | 314 | 55 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | yes | new_label:credit_rating | credit rating assigned by rating agencies |
| 6 | `environment` | 2,546 | 180 | 47 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | no: bucket word | new_label:environment | environmental metrics and disclosures |
| 7 | `energy` | 2,335 | 190 | 51 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (11) | no: bucket word | new_label:energy | energy consumption and efficiency |
| 8 | `safety` | 2,227 | 163 | 45 | annual_report | 0/2 (0%) | 1/2 (50%) | - | no: bucket word | new_label:safety | safety incidents and practices |
| 9 | `fair_value` | 2,015 | 165 | 51 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:fair_value | fair value measurements |
| 10 | `environmental` | 2,232 | 109 | 43 | annual_report | 2/2 (100%) | 2/2 (100%) | - | no: bucket word | new_label:environment | environmental metrics and disclosures |
| 11 | `training` | 1,998 | 181 | 48 | annual_report | 0/2 (0%) | 2/2 (100%) | - | no: bucket word | new_label:training | employee training hours and programs |
| 12 | `Others` | 1,839 | 369 | 40 | deck | 2/2 (100%) | 2/2 (100%) | exact (5) | no: only non-topic words | meaningless |  |
| 13 | `derivatives` | 2,043 | 124 | 38 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (1) | yes | new_label:derivatives | derivative instruments and exposures |
| 14 | `compliance` | 1,509 | 275 | 57 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (1) | no: bucket word | new_label:compliance | regulatory and statutory compliance |
| 15 | `hedging` | 1,890 | 112 | 37 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (5) | no: bucket word | new_label:hedging | hedging instruments and coverage |
| 16 | `water` | 1,795 | 121 | 44 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | no: bucket word | new_label:water | water consumption and usage |
| 17 | `operational` | 1,890 | 97 | 38 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (1) | no: bucket word | bucket:section |  |
| 18 | `sustainability` | 1,634 | 143 | 44 | annual_report | 2/2 (100%) | 2/2 (100%) | - | no: bucket word | new_label:sustainability | sustainability and ESG initiatives |
| 19 | `Total` | 1,554 | 251 | 33 | deck | 2/2 (100%) | 2/2 (100%) | exact (10) | no: only non-topic words | meaningless |  |
| 20 | `foreign_exchange` | 1,309 | 238 | 57 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:foreign_exchange | foreign exchange earnings and exposures |
| 21 | `capital_commitment` | 1,295 | 245 | 55 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:capital_commitment | capital commitments and pending contracts |
| 22 | `caro` | 1,361 | 152 | 54 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:caro | CARO audit reporting matters |
| 23 | `waste` | 1,507 | 102 | 42 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | no: bucket word | new_label:waste | waste generation and disposal |
| 24 | `fair_value_hierarchy` | 1,474 | 85 | 34 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:fair_value_hierarchy | fair value hierarchy levels |
| 25 | `AUM` | 1,893 | 129 | 7 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (3) | no: bucket word | new_label:aum | assets under management |
| 26 | `emissions` | 1,238 | 102 | 41 | annual_report | 2/2 (100%) | 2/2 (100%) | stem (1) | yes | new_label:emissions | greenhouse gas emissions |
| 27 | `industry` | 1,229 | 92 | 43 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (26) | yes | bucket:section |  |
| 28 | `capital_commitments` | 1,002 | 221 | 52 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:capital_commitment | capital commitments and pending contracts |
| 29 | `corporate_action` | 1,015 | 186 | 53 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (6) | yes | new_label:corporate_action | dividends and corporate actions |
| 30 | `liquidity` | 996 | 148 | 41 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (2) | yes | new_label:liquidity | liquidity and funding position |
| 31 | `exceptional_items` | 992 | 146 | 38 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:exceptional_items | exceptional and one-off items |
| 32 | `macro` | 997 | 102 | 39 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (5) | yes | new_label:macro | macroeconomic indicators |
| 33 | `complaints` | 873 | 140 | 50 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:complaints | complaints received and resolved |
| 34 | `goodwill` | 886 | 145 | 33 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (1) | yes | new_label:goodwill | goodwill and intangible assets |
| 35 | `fleet` | 958 | 83 | 33 | annual_report | 0/2 (0%) | 1/2 (50%) | exact (2) | yes | new_label:fleet | fleet and plant network |
| 36 | `-` | 726 | 270 | 42 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 37 | `capital` | 744 | 148 | 53 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (33) | yes | new_label:capital | capital structure and inputs |
| 38 | `fx_exposure` | 824 | 104 | 42 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:fx_exposure | foreign currency exposure |
| 39 | `corporate` | 761 | 109 | 47 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (9) | yes | bucket:section |  |
| 40 | `esg` | 799 | 94 | 40 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:esg | ESG performance and ratings |
| 41 | `17` | 863 | 59 | 25 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 42 | `exceptional_item` | 665 | 130 | 39 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:exceptional_item | non-recurring items affecting profit |
| 43 | `foreign_currency_exposure` | 752 | 60 | 30 | annual_report | 0/2 (0%) | 2/2 (100%) | list (1) | yes | new_label:foreign_currency_exposure | foreign currency exposure |
| 44 | `capital_structure` | 603 | 120 | 45 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:capital_structure | capital structure |
| 45 | `listing` | 514 | 191 | 57 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (161) | yes | new_label:listing | stock exchange listings |
| 46 | `procurement` | 594 | 99 | 36 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | yes | new_label:procurement | purchasing and sourcing |
| 47 | `market` | 593 | 86 | 40 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (44) | yes | bucket:market_data |  |
| 48 | `human_rights_training` | 599 | 81 | 40 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:human_rights_training | human rights training |
| 49 | `certification` | 519 | 143 | 46 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:certification | certifications |
| 50 | `energy_consumption` | 625 | 62 | 34 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:energy_consumption | energy consumption |
| 51 | `discontinued_operations` | 746 | 46 | 18 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:discontinued_operations | discontinued operations |
| 52 | `derivative` | 679 | 47 | 26 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (1) | yes | new_label:derivative | derivative instruments |
| 53 | `1` | 462 | 238 | 37 | deck | 2/2 (100%) | 2/2 (100%) | - | no: no letters (number/uni | meaningless |  |
| 54 | `fx_sensitivity` | 532 | 94 | 38 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:fx_sensitivity | foreign exchange sensitivity |
| 55 | `sensitivity` | 633 | 54 | 27 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (1) | yes | new_label:sensitivity | sensitivity analysis |
| 56 | `Area Booked` | 1,815 | 31 | 1 | deck | 2/2 (100%) | 2/2 (100%) | token (63) | yes | bucket:deck_line |  |
| 57 | `project` | 639 | 61 | 23 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (5) | yes | new_label:project | projects and initiatives |
| 58 | `foreign exchange` | 504 | 95 | 47 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:foreign_exchange | foreign exchange |
| 59 | `litigation` | 459 | 144 | 48 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:litigation | litigation matters |
| 60 | `industry_data` | 651 | 41 | 27 | annual_report | 0/2 (0%) | 2/2 (100%) | token (26) | yes | bucket:section |  |
| 61 | `3` | 430 | 256 | 41 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 62 | `operational_metric` | 612 | 55 | 27 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | bucket:ratio |  |
| 63 | `grievances` | 509 | 92 | 39 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:grievances | grievances and complaints |
| 64 | `human_rights` | 494 | 93 | 42 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:human_rights | human rights |
| 65 | `commitments` | 499 | 96 | 38 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (1) | yes | new_label:commitments | commitments |
| 66 | `2` | 412 | 256 | 40 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 67 | `disputed_statutory_dues` | 692 | 32 | 20 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:disputed_statutory_dues | disputed statutory dues |
| 68 | `msme` | 436 | 120 | 50 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (1) | yes | new_label:msme | micro and small enterprises |
| 69 | `assurance` | 469 | 97 | 36 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | yes | new_label:assurance | assurance providers |
| 70 | `performance` | 506 | 61 | 36 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 71 | `Environmental` | 816 | 19 | 13 | annual_report | 0/2 (0%) | 2/2 (100%) | - | no: bucket word | bucket:section |  |
| 72 | `rnd` | 486 | 78 | 30 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:rnd | research and development |
| 73 | `CARO` | 496 | 53 | 35 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 74 | `caro_remark` | 513 | 49 | 31 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:section |  |
| 75 | `credit rating` | 420 | 106 | 39 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | yes | new_label:credit_rating | credit ratings |
| 76 | `iepf` | 386 | 121 | 48 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:iepf | investor education and protection fund |
| 77 | `ratios` | 544 | 36 | 28 | annual_report | 0/2 (0%) | 2/2 (100%) | stem (16) | no: only non-topic words | bucket:ratio |  |
| 78 | `legal` | 356 | 147 | 51 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:legal | legal matters |
| 79 | `agm` | 342 | 140 | 54 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (2) | yes | new_label:agm | annual general meeting |
| 80 | `social` | 468 | 53 | 27 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:section |  |
| 81 | `Value of Area Booked` | 1,325 | 31 | 1 | deck | 2/2 (100%) | 2/2 (100%) | token (63) | yes | bucket:deck_line |  |
| 82 | `Grand Total` | 619 | 79 | 6 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | meaningless |  |
| 83 | `fair value` | 532 | 28 | 22 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:fair_value | valuation basis of assets and liabilities |
| 84 | `grievance` | 384 | 68 | 33 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:grievance | stakeholder complaints raised |
| 85 | `struck_off_companies` | 404 | 68 | 26 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:section |  |
| 86 | `4` | 313 | 192 | 35 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 87 | `buyback` | 446 | 58 | 18 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (6) | yes | new_label:buyback | repurchase of company shares |
| 88 | `Year` | 510 | 36 | 15 | deck | 2/2 (100%) | 0/2 (0%) | exact (63) | no: only stop/non-topic wo | bucket:table_header |  |
| 89 | `commitment` | 370 | 72 | 33 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (1) | yes | new_label:capital_commitment | estimated capital contracts remaining to be executed |
| 90 | `ESG` | 400 | 58 | 27 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:esg | environmental social governance performance |
| 91 | `corporate_event` | 310 | 109 | 48 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | bucket:section |  |
| 92 | `Exceptional items` | 425 | 95 | 13 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:exceptional_items | one-off gains or losses |
| 93 | `200` | 1,015 | 10 | 3 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 94 | `Saleable Area (Lakhs sq ft)` | 1,232 | 18 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 95 | `forex` | 330 | 68 | 42 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | yes | new_label:forex | foreign exchange earnings or exposure |
| 96 | `Exceptional Items` | 361 | 98 | 17 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:exceptional_items | one-off gains or losses |
| 97 | `diversity` | 353 | 59 | 28 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:diversity | workforce diversity metrics |
| 98 | `Equivalent Area Constructed*` | 1,031 | 31 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 99 | `corporate_info` | 303 | 78 | 41 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 100 | `award` | 308 | 86 | 34 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (9) | yes | new_label:award | recognition received by company |
| 101 | `01` | 285 | 164 | 28 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 102 | `consumer_complaints` | 314 | 64 | 36 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:consumer_complaints | complaints from consumers |
| 103 | `ghg_emissions` | 358 | 46 | 26 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:ghg_emissions | greenhouse gas emissions |
| 104 | `02` | 276 | 167 | 29 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 105 | `exceptional items` | 328 | 64 | 27 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:exceptional_items | one-off gains or losses |
| 106 | `03` | 268 | 173 | 30 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 107 | `committee_attendance` | 370 | 32 | 27 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:committee_attendance | board committee meeting attendance |
| 108 | `metric` | 604 | 16 | 7 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (2) | yes | meaningless |  |
| 109 | `strategy` | 267 | 93 | 44 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:strategy | strategic plans and targets |
| 110 | `5` | 263 | 147 | 31 | deck | 2/2 (100%) | 2/2 (100%) | - | no: no letters (number/uni | meaningless |  |
| 111 | `offsetting` | 537 | 27 | 6 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:offsetting | netting of financial assets and liabilities |
| 112 | `capital commitment` | 283 | 64 | 36 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:capital_commitment | estimated capital contracts remaining to be executed |
| 113 | `safety_incidents` | 334 | 38 | 27 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:safety_incidents | workplace safety incidents |
| 114 | `distribution` | 320 | 53 | 23 | annual_report | 0/2 (0%) | 1/2 (50%) | exact (4) | yes | new_label:distribution | dealer and distribution network |
| 115 | `Goodwill` | 355 | 85 | 10 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (1) | yes | new_label:goodwill | intangible asset from acquisitions |
| 116 | `leverage` | 288 | 70 | 27 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (3) | yes | new_label:leverage | debt relative to equity or earnings |
| 117 | `Total Outflows (C)` | 591 | 66 | 2 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 118 | `energy_conservation` | 286 | 59 | 29 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:energy_conservation | energy saving initiatives |
| 119 | `contract_balances` | 299 | 61 | 23 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:contract_balances | balances from customer contracts |
| 120 | `r_and_d` | 345 | 35 | 20 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (61) | yes | new_label:r_and_d | research and development spend |
| 121 | `restatement` | 292 | 47 | 30 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:restatement | revision of prior financial statements due to errors |
| 122 | `TOTAL` | 351 | 63 | 9 | deck | 2/2 (100%) | 2/2 (100%) | exact (10) | no: only non-topic words | meaningless |  |
| 123 | `marketing` | 309 | 45 | 19 | annual_report | 0/2 (0%) | 1/2 (50%) | exact (42) | yes | new_label:marketing | promotional and customer outreach activities |
| 124 | `air_emissions` | 278 | 45 | 30 | annual_report | 0/2 (0%) | 0/2 (0%) | - | yes | new_label:air_emissions | gaseous pollutants released to atmosphere |
| 125 | `Scrip Code` | 208 | 203 | 30 | deck | 2/2 (100%) | 0/2 (0%) | exact (3) | yes | bucket:table_header |  |
| 126 | `Capital Employed` | 346 | 75 | 7 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:capital_employed | total capital used in business |
| 127 | `divestment` | 244 | 68 | 30 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:divestment | sale or disposal of assets or businesses |
| 128 | `consolidation` | 306 | 31 | 22 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:consolidation | combining financial statements of subsidiaries |
| 129 | `market_position` | 242 | 67 | 31 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:market_position | competitive standing in market |
| 130 | `maturity_analysis` | 443 | 15 | 9 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:maturity_analysis | timing of financial liabilities |
| 131 | `fair value hierarchy` | 342 | 22 | 17 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:fair_value_hierarchy | valuation input levels |
| 132 | `water_withdrawal` | 247 | 43 | 29 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:water_withdrawal | water taken from sources |
| 133 | `nci` | 284 | 33 | 20 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (17) | yes | new_label:nci | non-controlling interest in subsidiaries |
| 134 | `kmp` | 208 | 70 | 41 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (1) | yes | new_label:kmp | key managerial personnel |
| 135 | `sensitivity_analysis` | 297 | 26 | 20 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:sensitivity_analysis | effect of variable changes |
| 136 | `Domestic` | 316 | 58 | 8 | deck | 2/2 (100%) | 1/2 (50%) | exact (5) | no: only stop/non-topic wo | alias_of:geography |  |
| 137 | `04` | 199 | 131 | 26 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 138 | `concentration` | 288 | 29 | 18 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (1) | yes | new_label:concentration | reliance on few customers or suppliers |
| 139 | `oci` | 231 | 48 | 28 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (1) | yes | new_label:oci | other comprehensive income |
| 140 | `IEPF` | 210 | 60 | 34 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:iepf | investor education and protection fund |
| 141 | `renewable_energy` | 240 | 46 | 23 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (1) | yes | new_label:renewable_energy | energy from renewable sources |
| 142 | `maturity` | 328 | 19 | 14 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (2) | yes | new_label:maturity | due dates of liabilities |
| 143 | `actuarial_assumptions` | 267 | 31 | 20 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:actuarial_assumptions | assumptions for employee benefit valuations |
| 144 | `sourcing` | 199 | 66 | 36 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (1) | yes | new_label:sourcing | procurement of inputs |
| 145 | `guarantee` | 220 | 52 | 25 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:guarantee | third-party guarantee obligations |
| 146 | `Saleable Area` | 518 | 24 | 2 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:saleable_area | area available for sale |
| 147 | `Leverage ratio` | 517 | 24 | 2 | concall | 0/2 (0%) | 2/2 (100%) | exact (2) | yes | bucket:ratio |  |
| 148 | `sexual_harassment` | 180 | 79 | 40 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:sexual_harassment | workplace harassment cases |
| 149 | `unclaimed_shares` | 236 | 48 | 18 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:unclaimed_shares | shares unclaimed by shareholders |
| 150 | `investor_grievances` | 193 | 65 | 33 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:investor_grievances | complaints from investors |
| 151 | `other` | 205 | 44 | 34 | annual_report | 0/2 (0%) | 1/2 (50%) | exact (10) | no: only non-topic words | meaningless |  |
| 152 | `guarantees` | 212 | 58 | 22 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | alias_of:liability |  |
| 153 | `posh` | 183 | 63 | 40 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:posh | complaints under the POSH Act |
| 154 | `ghg` | 242 | 29 | 22 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:ghg | greenhouse gas emissions |
| 155 | `operational_metrics` | 285 | 21 | 15 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 156 | `foreign currency exposure` | 274 | 23 | 16 | annual_report | 0/2 (0%) | 2/2 (100%) | list (1) | yes | new_label:foreign_currency_exposure | unhedged currency risk |
| 157 | `brsr` | 216 | 35 | 27 | annual_report | 1/2 (50%) | 1/2 (50%) | - | yes | new_label:brsr | business responsibility sustainability reporting |
| 158 | `contract` | 206 | 50 | 24 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (17) | yes | new_label:contract | signed customer contracts |
| 159 | `intangibles` | 204 | 39 | 30 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | alias_of:asset |  |
| 160 | `company_info` | 194 | 43 | 33 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 161 | `human_rights_complaints` | 194 | 47 | 30 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:human_rights_complaints | complaints of human rights violations |
| 162 | `foreign_currency` | 247 | 27 | 17 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | yes | new_label:foreign_currency | foreign currency amounts and expenditure |
| 163 | `parental_leave` | 183 | 55 | 33 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:parental_leave | parental leave and return-to-work rates |
| 164 | `research_development` | 204 | 47 | 22 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:research_development | research and development activity |
| 165 | `liquidity_maturity` | 285 | 16 | 14 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:liquidity_maturity | maturity profile of liabilities |
| 166 | `Area Booked (Lakhs sq ft)` | 621 | 16 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 167 | `Page number` | 152 | 132 | 32 | deck | 2/2 (100%) | 0/2 (0%) | - | yes | bucket:deck_line |  |
| 168 | `6` | 165 | 101 | 26 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 169 | `technology` | 170 | 66 | 32 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (9) | yes | new_label:technology | technology collaborations and patents |
| 170 | `Capital Adequacy` | 374 | 57 | 2 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:ratio |  |
| 171 | `investor_complaints` | 186 | 52 | 26 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:investor_complaints | investor grievances received |
| 172 | `2023` | 172 | 85 | 24 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 173 | `postal_ballot` | 183 | 45 | 30 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:postal_ballot | postal ballot resolutions |
| 174 | `network` | 254 | 26 | 12 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | yes | new_label:network | retail network and outlets |
| 175 | `Total Inflows (A)` | 542 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | stem (5) | yes | bucket:table_header |  |
| 176 | `general` | 169 | 53 | 35 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 177 | `caro_remarks` | 234 | 23 | 18 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | alias_of:auditor |  |
| 178 | `Other Outflows` | 536 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | stem (1) | yes | bucket:table_header |  |
| 179 | `partnership` | 173 | 54 | 29 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | yes | new_label:partnership | partnerships and collaborations |
| 180 | `Other inflows` | 531 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | stem (5) | yes | bucket:table_header |  |
| 181 | `capital_raising` | 161 | 63 | 34 | annual_report | 1/2 (50%) | 2/2 (100%) | stem (2) | yes | new_label:capital_raising | equity and capital raising |
| 182 | `2022` | 161 | 108 | 21 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 183 | `energy_intensity` | 182 | 43 | 26 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:energy_intensity | energy use per unit output |
| 184 | `hedge_accounting` | 263 | 23 | 10 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:hedge_accounting | hedge accounting adjustments |
| 185 | `macro_indicator` | 255 | 18 | 14 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:market_data |  |
| 186 | `disputed_dues` | 197 | 31 | 24 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:disputed_dues | disputed statutory dues |
| 187 | `2021` | 164 | 94 | 20 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 188 | `insolvency` | 194 | 35 | 22 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:insolvency | insolvency proceedings and settlements |
| 189 | `rd` | 175 | 44 | 28 | annual_report | 0/2 (0%) | 2/2 (100%) | - | no: two-letter fragment | new_label:research_development | research and development activity |
| 190 | `reclassification` | 204 | 32 | 19 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:reclassification | accounting reclassification |
| 191 | `exports` | 166 | 61 | 26 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (12) | yes | new_label:exports | export contribution and sales |
| 192 | `market data` | 217 | 25 | 18 | annual_report | 2/2 (100%) | 2/2 (100%) | token (42) | yes | bucket:market_data |  |
| 193 | `Slide Number` | 140 | 111 | 33 | deck | 2/2 (100%) | 0/2 (0%) | - | yes | bucket:deck_line |  |
| 194 | `corporate action` | 161 | 53 | 31 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (6) | yes | new_label:corporate_action | corporate actions and restructuring |
| 195 | `Training` | 275 | 14 | 11 | annual_report | 1/2 (50%) | 2/2 (100%) | - | no: bucket word | new_label:training | employee training hours |
| 196 | `Cumulative Total Inflows (B)` | 494 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 197 | `Cumulative Total Outflows (D)` | 494 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 198 | `certifications` | 145 | 64 | 38 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:certifications | certifications and standards |
| 199 | `Unsold Area (Lakhs sq ft)` | 536 | 16 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 200 | `Equivalent Area Constructed` | 473 | 26 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 201 | `stock_market_data` | 468 | 7 | 3 | annual_report | 2/2 (100%) | 2/2 (100%) | token (2) | yes | bucket:section |  |
| 202 | `human_resources` | 163 | 39 | 32 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 203 | `CRAR (standalone)` | 495 | 21 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:capital_adequacy_ratio | capital to risk-weighted assets ratio |
| 204 | `fraud` | 137 | 73 | 37 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:fraud | fraudulent activity reported or noted |
| 205 | `msmed_dues` | 203 | 31 | 14 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | alias_of:payable |  |
| 206 | `group_structure` | 170 | 36 | 24 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | bucket:section |  |
| 207 | `digital` | 172 | 38 | 21 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:digital | digital initiatives and technology adoption |
| 208 | `Slide number` | 134 | 94 | 28 | deck | 2/2 (100%) | 0/2 (0%) | - | yes | bucket:deck_line |  |
| 209 | `claims` | 142 | 54 | 34 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (5) | yes | new_label:claims | claims submitted or pending |
| 210 | `Cumulative mismatch (F = B-D)` | 450 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 211 | `Environment` | 194 | 31 | 14 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | no: bucket word | new_label:environment | environmental and sustainability matters |
| 212 | `Sensitivity Analysis` | 275 | 11 | 9 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:section |  |
| 213 | `intellectual_property` | 165 | 44 | 18 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:intellectual_property | patents and IP filings |
| 214 | `value_chain` | 134 | 61 | 33 | annual_report | 0/2 (0%) | 2/2 (100%) | token (13) | yes | new_label:value_chain | value chain partners and assessment |
| 215 | `Mismatch (E = A - C)` | 433 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 216 | `performance_review` | 163 | 35 | 22 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:performance_review | employee performance and career reviews |
| 217 | `Waste` | 212 | 23 | 11 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | no: bucket word | new_label:waste | waste generation and management |
| 218 | `Cumulative mismatch as % (F/D)` | 431 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 219 | `PBDT` | 352 | 22 | 2 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:pbdt | profit before depreciation and tax |
| 220 | `company_profile` | 142 | 46 | 30 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 221 | `macro_economy` | 252 | 12 | 10 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:macro_economy | macroeconomic indicators and outlook |
| 222 | `Solar` | 252 | 36 | 4 | deck | 2/2 (100%) | 2/2 (100%) | exact (3) | yes | alias_of:segment |  |
| 223 | `AOC-1` | 387 | 5 | 5 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 224 | `awards` | 152 | 41 | 22 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (9) | yes | new_label:awards | awards and recognitions received |
| 225 | `50` | 162 | 43 | 16 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 226 | `2015` | 117 | 105 | 31 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 227 | `esg_rating` | 153 | 38 | 22 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:esg_rating | ESG rating assigned by agencies |
| 228 | `AGM` | 131 | 47 | 36 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (2) | yes | new_label:agm | annual general meeting details |
| 229 | `Liquidity` | 199 | 69 | 5 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (2) | yes | new_label:liquidity | cash and liquidity position |
| 230 | `Energy` | 194 | 29 | 10 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (11) | no: bucket word | new_label:energy | energy consumption and sources |
| 231 | `statutory_dues` | 127 | 48 | 36 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:statutory_dues | statutory dues payable or deposited |
| 232 | `finance` | 187 | 19 | 16 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (20) | yes | bucket:section |  |
| 233 | `BRSR` | 172 | 24 | 18 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 234 | `Operations` | 156 | 29 | 21 | annual_report | 0/2 (0%) | 0/2 (0%) | exact (3) | yes | bucket:section |  |
| 235 | `financing` | 141 | 40 | 24 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (3) | yes | new_label:financing | financing arrangements and credit |
| 236 | `05` | 118 | 92 | 25 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 237 | `disclosure` | 130 | 40 | 32 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (17) | yes | new_label:disclosure | regulatory and sustainability disclosures |
| 238 | `water_intensity` | 138 | 37 | 25 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:water_intensity | water use per unit of output |
| 239 | `NBFC` | 250 | 62 | 2 | deck | 2/2 (100%) | 2/2 (100%) | exact (12) | yes | bucket:entity |  |
| 240 | `markets` | 116 | 56 | 31 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (42) | yes | alias_of:geography |  |
| 241 | `valuation` | 151 | 28 | 18 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (6) | yes | new_label:valuation | estimated value of an asset, company or investment |
| 242 | `economic_value` | 196 | 18 | 9 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:economic_value | value generated by the company for stakeholders |
| 243 | `gearing` | 156 | 30 | 13 | annual_report | 0/2 (0%) | 2/2 (100%) | stem (1) | yes | new_label:gearing | leverage ratio of debt to equity |
| 244 | `union_membership` | 126 | 36 | 25 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:union_membership | employees or workers in recognised unions |
| 245 | `biodiversity` | 161 | 24 | 13 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:biodiversity | biological diversity impacts and targets |
| 246 | `r&d` | 176 | 16 | 13 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (61) | yes | new_label:research_and_development | research and development expenditure or activity |
| 247 | `assessment` | 121 | 43 | 24 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | meaningless |  |
| 248 | `10` | 102 | 87 | 27 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 249 | `safety_performance` | 234 | 11 | 6 | annual_report | 0/2 (0%) | 1/2 (50%) | - | yes | new_label:safety_performance | workplace safety incidents and fatalities |
| 250 | `value_chain_assessment` | 108 | 49 | 33 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:value_chain_assessment | assessment of value chain partners |
| 251 | `discontinued operations` | 168 | 19 | 12 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:discontinued_operations | profit or loss from discontinued operations |
| 252 | `Company` | 367 | 7 | 2 | deck | 2/2 (100%) | 2/2 (100%) | exact (165) | yes | bucket:table_header |  |
| 253 | `Saleable Area (Lakhs Sq. ft.)` | 359 | 17 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:saleable_area | saleable real estate area |
| 254 | `dematerialization` | 119 | 38 | 25 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:dematerialization | shares held in dematerialized form |
| 255 | `waste_generated` | 163 | 16 | 15 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:waste_generated | total waste generated |
| 256 | `innovation` | 132 | 39 | 15 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:innovation | ideas, patents or innovation activity |
| 257 | `fair value measurement` | 188 | 13 | 10 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:fair_value_measurement | fair value hierarchy measurements |
| 258 | `7` | 107 | 73 | 21 | deck | 2/2 (100%) | 2/2 (100%) | - | no: no letters (number/uni | meaningless |  |
| 259 | `Footnote` | 147 | 32 | 11 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 260 | `Total Value (INR Crores)` | 390 | 11 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | no: only non-topic words | bucket:table_header |  |
| 261 | `Unsold Value (INR Crores)` | 390 | 11 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 262 | `suspense_account` | 130 | 33 | 17 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:suspense_account | shares or folios in suspense escrow account |
| 263 | `Other` | 144 | 63 | 7 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (10) | no: only non-topic words | meaningless |  |
| 264 | `title_deeds` | 142 | 22 | 17 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:title_deeds | property title deed status |
| 265 | `emphasis_of_matter` | 112 | 48 | 22 | annual_report | 1/2 (50%) | 2/2 (100%) | token (1) | yes | new_label:emphasis_of_matter | auditor emphasis of matter paragraphs |
| 266 | `actuarial_assumption` | 146 | 21 | 15 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:actuarial_assumption | assumptions used in benefit obligation valuation |
| 267 | `2020` | 109 | 65 | 18 | deck | 2/2 (100%) | 2/2 (100%) | - | no: no letters (number/uni | meaningless |  |
| 268 | `water_consumption` | 133 | 28 | 16 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:water_consumption | total water consumed |
| 269 | `ECB` | 246 | 26 | 2 | deck | 2/2 (100%) | 2/2 (100%) | exact (1) | yes | alias_of:debt |  |
| 270 | `research and development` | 167 | 15 | 11 | annual_report | 0/2 (0%) | 1/2 (50%) | - | yes | new_label:research_and_development | research and development expenditure or activity |
| 271 | `training_coverage` | 125 | 27 | 20 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:training_coverage | employees covered by training |
| 272 | `18` | 93 | 86 | 26 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 273 | `20` | 92 | 82 | 27 | deck | 2/2 (100%) | 2/2 (100%) | - | no: no letters (number/uni | meaningless |  |
| 274 | `Sustainability` | 129 | 27 | 16 | annual_report | 0/2 (0%) | 2/2 (100%) | - | no: bucket word | new_label:sustainability | sustainability targets and metrics |
| 275 | `2024` | 106 | 52 | 20 | deck | 2/2 (100%) | 2/2 (100%) | - | no: no letters (number/uni | meaningless |  |
| 276 | `sensitivity analysis` | 184 | 11 | 9 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:sensitivity_analysis | sensitivity of valuations to assumption changes |
| 277 | `fundraising` | 97 | 51 | 29 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:fundraising | raising funds via securities |
| 278 | `currency_exposure` | 189 | 11 | 8 | annual_report | 0/2 (0%) | 2/2 (100%) | list (1) | yes | new_label:currency_exposure | unhedged foreign currency exposure |
| 279 | `struck off companies` | 182 | 10 | 10 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:struck_off_companies | balances with struck off companies |
| 280 | `collateral` | 131 | 32 | 12 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (1) | yes | new_label:collateral | assets pledged as collateral |
| 281 | `struck_off_company` | 141 | 22 | 12 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:struck_off_company | companies struck off the register |
| 282 | `Cumulative gap upto 1 month` | 291 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 283 | `environment-waste` | 204 | 9 | 7 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:environment_waste | waste generation and disposal |
| 284 | `AHL (Area in Sq. Ft.)` | 469 | 4 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 285 | `30` | 90 | 70 | 28 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 286 | `actuarial assumption` | 160 | 14 | 11 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:actuarial_assumption | assumptions for employee benefit liabilities |
| 287 | `Tier 1 Capital` | 292 | 23 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:tier_1_capital | bank tier 1 regulatory capital |
| 288 | `Tier 2 Capital` | 292 | 23 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:tier_2_capital | bank tier 2 regulatory capital |
| 289 | `corporate_identity` | 100 | 41 | 27 | annual_report | 0/2 (0%) | 1/2 (50%) | - | yes | bucket:table_header |  |
| 290 | `Operational` | 161 | 33 | 5 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (1) | no: bucket word | bucket:section |  |
| 291 | `key_ratio` | 166 | 14 | 9 | annual_report | 0/2 (0%) | 0/2 (0%) | token (8) | yes | bucket:table_header |  |
| 292 | `2019` | 104 | 70 | 14 | deck | 2/2 (100%) | 2/2 (100%) | - | no: no letters (number/uni | meaningless |  |
| 293 | `8` | 94 | 67 | 22 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 294 | `Availability under committed credit facilities` | 291 | 21 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:credit_facility_availability | unused committed credit lines |
| 295 | `Foreign Currency Exposure` | 219 | 7 | 6 | annual_report | 0/2 (0%) | 2/2 (100%) | list (1) | yes | new_label:foreign_currency_exposure | exposure to foreign currency risk |
| 296 | `penalty` | 116 | 27 | 18 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (1) | yes | new_label:penalty | penalties and fines imposed |
| 297 | `Water` | 148 | 23 | 8 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | no: bucket word | new_label:water_usage | water withdrawal and consumption |
| 298 | `forex_exposure` | 152 | 14 | 11 | annual_report | 0/2 (0%) | 2/2 (100%) | list (1) | yes | new_label:forex_exposure | foreign currency exposure |
| 299 | `water_discharge` | 109 | 29 | 21 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:water_discharge | water discharged |
| 300 | `COF` | 277 | 23 | 1 | deck | 2/2 (100%) | 2/2 (100%) | exact (2) | yes | new_label:cost_of_funds | cost of funds |
| 301 | `exceptional item` | 102 | 35 | 23 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:exceptional_item | exceptional items |
| 302 | `2017` | 98 | 83 | 13 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 303 | `recognition` | 107 | 31 | 20 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (1) | yes | new_label:recognition | awards and recognitions |
| 304 | `contracts` | 86 | 53 | 32 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (13) | yes | new_label:contracts | long-term contracts |
| 305 | `brsr_training` | 144 | 16 | 11 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:brsr_training | BRSR training coverage |
| 306 | `Leverage Ratio` | 277 | 21 | 1 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | yes | new_label:leverage_ratio | leverage ratio |
| 307 | `Ratio` | 166 | 10 | 10 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (45) | no: only non-topic words | bucket:table_header |  |
| 308 | `Cross sell franchise` | 268 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:cross_sell_franchise | cross-sell franchise value |
| 309 | `Total AUM` | 169 | 40 | 3 | concall | 2/2 (100%) | 2/2 (100%) | token (3) | yes | new_label:aum | assets under management |
| 310 | `Urban B2C` | 314 | 12 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:urban_b2c | urban b2c portfolio |
| 311 | `2025` | 89 | 49 | 27 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 312 | `plant_location` | 122 | 20 | 16 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 313 | `corporate_guarantee` | 128 | 24 | 11 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:corporate_guarantee | corporate guarantees |
| 314 | `Cumulative gap upto 12 month` | 268 | 22 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 315 | `credit_quality` | 132 | 18 | 12 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:credit_quality | credit quality metrics |
| 316 | `market_size` | 129 | 18 | 13 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:market_size | market size |
| 317 | `facility` | 113 | 29 | 14 | annual_report | 1/2 (50%) | 2/2 (100%) | stem (22) | yes | new_label:facility | facility or center |
| 318 | `Corporate` | 143 | 47 | 4 | deck | 2/2 (100%) | 2/2 (100%) | exact (9) | yes | bucket:table_header |  |
| 319 | `foreign_currency_sensitivity` | 133 | 16 | 12 | annual_report | 2/2 (100%) | 2/2 (100%) | list (1) | yes | new_label:foreign_currency_sensitivity | sensitivity to currency movements |
| 320 | `corporate_structure` | 102 | 29 | 20 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:corporate_structure | corporate structure |
| 321 | `natural_capital` | 139 | 16 | 10 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:natural_capital | natural assets and ecosystem resources |
| 322 | `hedge_reserve` | 210 | 9 | 4 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:hedge_reserve | reserve for cash flow hedge effectiveness |
| 323 | `maturity profile` | 156 | 10 | 10 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 324 | `LCV` | 269 | 18 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | alias_of:product |  |
| 325 | `2010` | 86 | 79 | 16 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 326 | `12` | 81 | 65 | 24 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 327 | `Leverage Threshold` | 256 | 21 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:leverage_threshold | maximum permitted leverage ratio |
| 328 | `Total Capital Adequacy Ratio (CRAR)` | 258 | 20 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:capital_adequacy | regulatory capital adequacy ratio |
| 329 | `capital_markets` | 126 | 15 | 14 | annual_report | 2/2 (100%) | 2/2 (100%) | stem (1) | yes | new_label:capital_markets | equity and debt fundraising activities |
| 330 | `15` | 80 | 74 | 22 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 331 | `28` | 80 | 66 | 23 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 332 | `Retail Stores` | 260 | 18 | 1 | deck | 2/2 (100%) | 0/2 (0%) | - | yes | new_label:retail_stores | number of retail stores |
| 333 | `ownership` | 95 | 31 | 21 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (10) | yes | alias_of:shareholding |  |
| 334 | `per_share` | 95 | 28 | 22 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (60) | no: only non-topic words | bucket:unit |  |
| 335 | `community` | 106 | 22 | 17 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | alias_of:csr |  |
| 336 | `Industry Data` | 250 | 4 | 4 | annual_report | 0/2 (0%) | 2/2 (100%) | token (26) | yes | bucket:section |  |
| 337 | `19` | 77 | 71 | 23 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 338 | `energy conservation` | 113 | 20 | 14 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:energy_conservation | energy saving initiatives and equipment |
| 339 | `schedule_iii` | 185 | 7 | 6 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 340 | `AHL` | 375 | 4 | 1 | deck | 2/2 (100%) | 2/2 (100%) | exact (1) | yes | bucket:entity |  |
| 341 | `fx` | 108 | 22 | 14 | annual_report | 0/2 (0%) | 2/2 (100%) | token (5) | no: two-letter fragment | new_label:fx | foreign exchange rates and impacts |
| 342 | `Maturity Analysis` | 212 | 5 | 5 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 343 | `22` | 75 | 68 | 23 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 344 | `capital_adequacy` | 157 | 19 | 4 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:capital_adequacy | regulatory capital adequacy ratio |
| 345 | `Particulars (INR Mn)` | 295 | 4 | 2 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 346 | `Distributors` | 141 | 28 | 4 | deck | 2/2 (100%) | 2/2 (100%) | stem (4) | yes | new_label:distributors | number of distributors |
| 347 | `2014` | 84 | 77 | 12 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 348 | `consumer complaints` | 97 | 22 | 18 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:consumer_complaints | complaints received and resolved |
| 349 | `safety_incident` | 117 | 14 | 13 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:safety_incident | workplace safety incidents |
| 350 | `General Insurance` | 193 | 45 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | alias_of:segment |  |
| 351 | `aoc1` | 277 | 3 | 3 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 352 | `reconciliation` | 124 | 13 | 11 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 353 | `demerger` | 111 | 19 | 11 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (7) | yes | new_label:demerger | separation of a business into independent entity |
| 354 | `environmental_compliance` | 74 | 42 | 28 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:environmental_compliance | compliance with environmental regulations |
| 355 | `Jaipur` | 163 | 32 | 2 | deck | 2/2 (100%) | 1/2 (50%) | - | yes | bucket:entity |  |
| 356 | `vigilance` | 151 | 17 | 4 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:vigilance | vigilance complaints and cases |
| 357 | `statutory_group_info` | 430 | 2 | 1 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 358 | `human_rights_assessment` | 74 | 39 | 29 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:human_rights_assessment | human rights due diligence coverage |
| 359 | `25` | 71 | 62 | 23 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 360 | `PCR (%)` | 174 | 23 | 2 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:pcr | provision coverage ratio |
| 361 | `RE 100` | 208 | 11 | 2 | deck | 2/2 (100%) | 0/2 (0%) | token (4) | yes | bucket:entity |  |
| 362 | `Net gain on fair value changes` | 245 | 13 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:net_gain_on_fair_value_changes | net gain from fair value changes in financial instruments |
| 363 | `Other, net` | 220 | 20 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | no: only non-topic words | bucket:table_header |  |
| 364 | `esg_waste` | 138 | 9 | 9 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:waste | total waste generated |
| 365 | `convertible_instruments` | 75 | 38 | 26 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:convertible_instruments | convertible debt instruments outstanding |
| 366 | `Fines/Lumps/Pellets` | 261 | 10 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 367 | `9` | 72 | 59 | 21 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 368 | `project_status` | 106 | 20 | 11 | annual_report | 2/2 (100%) | 2/2 (100%) | token (1) | yes | new_label:project_status | status of projects under execution |
| 369 | `insurance` | 83 | 32 | 19 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (6) | yes | new_label:insurance | insurance coverage and policies |
| 370 | `joint_operation` | 121 | 19 | 7 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | alias_of:jv |  |
| 371 | `Complaints` | 97 | 19 | 16 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 372 | `waste_disposal` | 108 | 15 | 13 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:waste_disposal | waste disposed safely |
| 373 | `Solvency Ratio` | 178 | 49 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:ratio |  |
| 374 | `actuarial assumptions` | 119 | 12 | 11 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:actuarial_assumptions | assumptions used in actuarial valuation |
| 375 | `Disbursements` | 118 | 68 | 3 | concall | 2/2 (100%) | 2/2 (100%) | exact (10) | yes | new_label:disbursement | loan disbursements made |
| 376 | `fund_raising` | 82 | 30 | 20 | annual_report | 1/2 (50%) | 2/2 (100%) | stem (2) | yes | new_label:fund_raising | funds raised during the period |
| 377 | `legal_proceedings` | 82 | 31 | 19 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:legal_proceedings | ongoing legal proceedings |
| 378 | `2013` | 79 | 73 | 11 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 379 | `fair_value_level3` | 102 | 19 | 12 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:fair_value_level3 | level 3 fair value measurements |
| 380 | `intellectual_capital` | 95 | 23 | 13 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:intellectual_capital | intellectual capital developments |
| 381 | `Umang` | 202 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:entity |  |
| 382 | `Credit Rating` | 93 | 20 | 16 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | yes | new_label:credit_rating | credit rating assigned |
| 383 | `exchange_rate` | 95 | 21 | 14 | annual_report | 2/2 (100%) | 2/2 (100%) | token (11) | yes | new_label:exchange_rate | foreign exchange rates |
| 384 | `disputed_claim` | 93 | 25 | 13 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:disputed_claim | claims under dispute |
| 385 | `company` | 80 | 26 | 23 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (165) | yes | meaningless |  |
| 386 | `2018` | 75 | 57 | 15 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 387 | `Dwarka` | 199 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:entity |  |
| 388 | `technology_absorption` | 92 | 21 | 15 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:technology_absorption | technology absorption initiatives |
| 389 | `Page Number` | 64 | 63 | 26 | deck | 2/2 (100%) | 0/2 (0%) | - | yes | bucket:table_header |  |
| 390 | `13` | 67 | 57 | 23 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 391 | `esg_water` | 126 | 10 | 9 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:water | water withdrawal and usage |
| 392 | `Level 5` | 395 | 2 | 1 | deck | 2/2 (100%) | 0/2 (0%) | exact (6) | yes | bucket:table_header |  |
| 393 | `21` | 67 | 63 | 20 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 394 | `06` | 70 | 57 | 18 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 395 | `Prescription Ranking` | 280 | 6 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:prescription_ranking | prescription market ranking |
| 396 | `Tarang` | 195 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:entity |  |
| 397 | `sustainable_sourcing` | 65 | 44 | 30 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:sustainable_sourcing | sustainably sourced inputs |
| 398 | `security` | 73 | 35 | 22 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:security | security pledged or created |
| 399 | `health_safety` | 111 | 12 | 11 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:health_safety | health and safety metrics |
| 400 | `Nirmay` | 192 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:entity |  |
| 401 | `Shubham` | 187 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:entity |  |
| 402 | `ghg_intensity` | 86 | 20 | 16 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:ghg_intensity | greenhouse gas emissions per unit of output |
| 403 | `PVC Compounds` | 186 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | alias_of:product |  |
| 404 | `derivative instruments` | 232 | 3 | 3 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:derivative_instruments | financial derivative contracts held |
| 405 | `gearing_ratio` | 101 | 18 | 9 | annual_report | 0/2 (0%) | 2/2 (100%) | stem (1) | yes | new_label:gearing_ratio | borrowings relative to equity |
| 406 | `ratio_analysis` | 135 | 9 | 6 | annual_report | 0/2 (0%) | 0/2 (0%) | - | yes | bucket:section |  |
| 407 | `CRAR` | 156 | 19 | 2 | concall | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:crar | capital to risk-weighted assets ratio |
| 408 | `Fair Value Hierarchy` | 132 | 8 | 7 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 409 | `stock_data` | 158 | 6 | 5 | annual_report | 2/2 (100%) | 2/2 (100%) | token (41) | yes | bucket:market_data |  |
| 410 | `WHRS` | 177 | 27 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:entity |  |
| 411 | `infrastructure` | 79 | 24 | 17 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (7) | yes | new_label:infrastructure | physical infrastructure assets |
| 412 | `Countries` | 75 | 51 | 11 | deck | 2/2 (100%) | 1/2 (50%) | exact (5) | yes | bucket:table_header |  |
| 413 | `plant_locations` | 76 | 28 | 17 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 414 | `operational_performance` | 101 | 14 | 10 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 415 | `milestone` | 78 | 23 | 17 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (2) | yes | bucket:section |  |
| 416 | `Fair Value` | 116 | 9 | 9 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 417 | `14` | 61 | 54 | 22 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 418 | `event` | 65 | 34 | 25 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (12) | yes | bucket:section |  |
| 419 | `posh_complaints` | 70 | 29 | 21 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:posh_complaints | sexual harassment complaints under POSH |
| 420 | `operational_data` | 128 | 8 | 7 | annual_report | 0/2 (0%) | 1/2 (50%) | token (1) | yes | bucket:table_header |  |
| 421 | `analytical_ratio` | 151 | 8 | 4 | annual_report | 0/2 (0%) | 0/2 (0%) | - | yes | bucket:ratio |  |
| 422 | `AUM (₹ ‘000 Cr)` | 225 | 9 | 1 | deck | 2/2 (100%) | 2/2 (100%) | exact (3) | no: bucket word | new_label:aum | assets under management |
| 423 | `11` | 63 | 45 | 22 | deck | 2/2 (100%) | 2/2 (100%) | - | no: no letters (number/uni | meaningless |  |
| 424 | `operating_metric` | 127 | 8 | 7 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 425 | `funding` | 87 | 18 | 13 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (27) | yes | new_label:funding | capital raised |
| 426 | `16` | 58 | 54 | 26 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 427 | `fair_value_measurement` | 118 | 9 | 8 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 428 | `actuarial` | 143 | 6 | 6 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 429 | `Net D/E` | 151 | 46 | 1 | deck | 2/2 (100%) | 2/2 (100%) | token (1) | yes | new_label:net_debt_to_equity | net debt divided by equity |
| 430 | `foreign currency` | 150 | 6 | 5 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | yes | new_label:foreign_currency_expenditure | spending in foreign currency |
| 431 | `credit ratings` | 74 | 24 | 18 | annual_report | 0/2 (0%) | 2/2 (100%) | stem (2) | yes | new_label:credit_rating | external credit assessment |
| 432 | `market_forecast` | 95 | 14 | 11 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:market_forecast | projected market demand |
| 433 | `Ginger` | 169 | 25 | 1 | deck | 2/2 (100%) | 1/2 (50%) | - | yes | bucket:entity |  |
| 434 | `per_share_data` | 121 | 10 | 6 | annual_report | 2/2 (100%) | 2/2 (100%) | token (10) | no: only non-topic words | bucket:table_header |  |
| 435 | `Exports` | 89 | 36 | 6 | concall | 1/2 (50%) | 2/2 (100%) | exact (12) | yes | new_label:exports | goods sold abroad |
| 436 | `31` | 61 | 57 | 17 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 437 | `legal_proceeding` | 69 | 29 | 18 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:legal_proceeding | pending litigation |
| 438 | `Bhiwadi` | 157 | 32 | 1 | concall | 1/2 (50%) | 1/2 (50%) | - | yes | bucket:entity |  |
| 439 | `Tenor (Years)` | 180 | 17 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 440 | `Area Booked (Lakhs Sq. ft.)` | 212 | 9 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 441 | `24` | 57 | 53 | 22 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 442 | `investor_grievance` | 78 | 19 | 15 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:investor_grievance | investor complaints and grievances |
| 443 | `Occupancy %` | 144 | 17 | 2 | deck | 2/2 (100%) | 2/2 (100%) | exact (3) | yes | alias_of:capacity_utilisation |  |
| 444 | `iepf_transfer` | 67 | 27 | 20 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:iepf_transfer | amounts transferred to investor protection fund |
| 445 | `S&P Global India Manufacturing PMI` | 193 | 12 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:market_data |  |
| 446 | `EV 100` | 202 | 10 | 1 | deck | 2/2 (100%) | 0/2 (0%) | token (8) | yes | new_label:ev100 | commitment to 100% electric vehicles |
| 447 | `AUM per cross sell franchise` | 175 | 17 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:aum_per_cross_sell_franchise | AUM per cross-sell franchise |
| 448 | `Operational ratios` | 231 | 6 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:section |  |
| 449 | `EP 100` | 200 | 10 | 1 | deck | 2/2 (100%) | 0/2 (0%) | - | yes | new_label:ep100 | energy productivity commitment |
| 450 | `26` | 59 | 50 | 18 | deck | 2/2 (100%) | 1/2 (50%) | - | no: no letters (number/uni | meaningless |  |
| 451 | `esg_energy` | 112 | 9 | 7 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:esg_energy | energy consumption metrics |
| 452 | `Ashiana Town` | 161 | 23 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 453 | `fair_value_sensitivity` | 96 | 14 | 8 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:fair_value_sensitivity | OCI impact from price changes |
| 454 | `Lifestyle retail stores` | 159 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 455 | `Total Bajaj Finance presence` | 159 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 456 | `Flats` | 197 | 10 | 1 | deck | 2/2 (100%) | 2/2 (100%) | stem (6) | yes | bucket:deck_line |  |
| 457 | `sector` | 107 | 9 | 8 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (22) | yes | bucket:table_header |  |
| 458 | `cyber_security` | 56 | 37 | 27 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:cyber_security | cyber security framework and policy |
| 459 | `Current Ratio` | 98 | 17 | 6 | deck | 2/2 (100%) | 2/2 (100%) | - | no: only non-topic words | bucket:ratio |  |
| 460 | `Anmol` | 156 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 461 | `Total (I + II)` | 159 | 22 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:table_header |  |
| 462 | `Network` | 152 | 11 | 2 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (2) | yes | new_label:network | service or distribution network |
| 463 | `1993` | 68 | 60 | 8 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 464 | `Total franchise` | 168 | 17 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 465 | `Capital Employed*` | 126 | 23 | 2 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:capital_employed | capital employed |
| 466 | `ESG-waste` | 151 | 5 | 4 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:esg_waste | waste generation metrics |
| 467 | `AHL Total` | 162 | 19 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 468 | `Traffic` | 162 | 19 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 469 | `Adjustment to reconcile proportional consolidation` | 165 | 17 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 470 | `Compliance` | 70 | 23 | 14 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (1) | no: bucket word | new_label:compliance | regulatory compliance disclosures |
| 471 | `Surbhi` | 151 | 24 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 472 | `Currency` | 141 | 13 | 2 | concall | 2/2 (100%) | 2/2 (100%) | exact (4) | yes | bucket:market_data |  |
| 473 | `Overall active distribution network` | 152 | 23 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 474 | `fx_hedging` | 85 | 14 | 10 | annual_report | 0/2 (0%) | 2/2 (100%) | token (2) | yes | new_label:fx_hedging | foreign exchange hedging |
| 475 | `Fee Paying AUM` | 136 | 37 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:fee_paying_aum | fee-paying assets under management |
| 476 | `Vrinda Gardens` | 150 | 23 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:deck_line |  |
| 477 | `demat` | 71 | 17 | 16 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | new_label:demat | dematerialised shareholding |
| 478 | `Longs` | 184 | 10 | 1 | deck | 2/2 (100%) | 2/2 (100%) | exact (24) | yes | bucket:deck_line |  |
| 479 | `lca` | 67 | 20 | 17 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (7) | yes | new_label:lca | life cycle assessment coverage |
| 480 | `RoW` | 97 | 17 | 5 | deck | 2/2 (100%) | 2/2 (100%) | exact (57) | yes | bucket:deck_line |  |
| 481 | `Fibre` | 192 | 4 | 2 | deck | 2/2 (100%) | 0/2 (0%) | exact (1) | yes | new_label:fibre | textile fibre product |
| 482 | `claim` | 66 | 26 | 14 | annual_report | 1/2 (50%) | 2/2 (100%) | exact (6) | yes | new_label:claim | amount claimed or claim receivable |
| 483 | `Presence` | 73 | 24 | 10 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:presence | distribution outlets or towns covered |
| 484 | `RevPAR in ₹` | 160 | 16 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:revpar | revenue per available room |
| 485 | `GHG Emissions` | 102 | 9 | 7 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:ghg_emissions | greenhouse gas emissions |
| 486 | `p_l` | 181 | 3 | 3 | annual_report | 0/2 (0%) | 0/2 (0%) | exact (7) | yes | bucket:table_header |  |
| 487 | `PCR` | 128 | 16 | 2 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:pcr | post-consumer recycled content |
| 488 | `human capital` | 78 | 15 | 11 | annual_report | 1/2 (50%) | 1/2 (50%) | - | yes | alias_of:employee |  |
| 489 | `capital structure` | 65 | 19 | 18 | annual_report | 1/2 (50%) | 2/2 (100%) | - | yes | new_label:capital_structure | mix of debt and equity |
| 490 | `note` | 67 | 17 | 17 | annual_report | 2/2 (100%) | 2/2 (100%) | exact (16) | yes | bucket:section |  |
| 491 | `registrar` | 47 | 45 | 31 | annual_report | 0/2 (0%) | 2/2 (100%) | - | yes | bucket:section |  |
| 492 | `Consumer` | 89 | 20 | 5 | annual_report | 0/2 (0%) | 2/2 (100%) | exact (8) | yes | alias_of:customer |  |
| 493 | `investor_relations` | 76 | 15 | 11 | annual_report | 2/2 (100%) | 2/2 (100%) | - | yes | bucket:section |  |
| 494 | `Affordability Index for Housing (By Metropolitan Area)` | 200 | 6 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:affordability_index | housing affordability index |
| 495 | `100` | 59 | 39 | 12 | deck | 2/2 (100%) | 2/2 (100%) | - | no: no letters (number/uni | meaningless |  |
| 496 | `Equivalent Area Constructed (Lakhs sq ft)` | 189 | 7 | 1 | deck | 2/2 (100%) | 2/2 (100%) | - | yes | new_label:equivalent_area_constructed | area constructed in equivalent units |
| 497 | `100%` | 60 | 32 | 13 | deck | 2/2 (100%) | 0/2 (0%) | - | no: no letters (number/uni | meaningless |  |
| 498 | `Partnership Total` | 145 | 19 | 1 | deck | 2/2 (100%) | 2/2 (100%) | stem (2) | yes | bucket:table_header |  |
| 499 | `DOMEX MULTI-PURPOSE DISINFECTANT SPRAY` | 341 | 1 | 1 | deck | 2/2 (100%) | 1/2 (50%) | - | yes | bucket:entity |  |
| 500 | `2016` | 58 | 51 | 10 | deck | 2/2 (100%) | 2/2 (100%) | - | no: no letters (number/uni | meaningless |  |

## 11. Context evidence for the top 60

| # | surface | excerpt 1 | excerpt 2 |
|---:|---|---|---|
| 1 | `signal` | Financial assistance received from government withheld citing confidentiality restrictions | Provisional attachment of DCBL land parcels indicates a legal/regulatory dispute over land assets |
| 2 | `ratio` | EBITDA margin | EBITDA margin |
| 3 | `market_data` | Segment-wise cement consumption - Urban housing | Segment-wise cement consumption - Industrial and commercial |
| 4 | `operations` | Sales volume growth from 29.4 MnT to 30.0 MnT | Sales Volume |
| 5 | `credit_rating` | ICRA ESG Ratings Limited (SEBI registered Category-I ESG Rating Provider) upgraded Company's ESG rating | CRISIL Ratings - Bank Facilities long-term rating |
| 6 | `environment` | Low carbon (blended) cement production share | Total waste generated (kg/tonne of cement) |
| 7 | `energy` | Energy intensity (TJ/KMT) | RE 100 commitment progress |
| 8 | `safety` | Safety inspections conducted annually | Fatalities |
| 9 | `fair_value` | Investment in equity shares measured at fair value (Level 1) | Investment in mutual funds measured at fair value (Level 2) |
| 10 | `environmental` | 8 operations/sites in/near ecologically sensitive areas; compliance status disclosed | EIA conducted by independent external agency for proposed standalone Grinding Unit at Pahur, Bindki, Fatehpur, |
| 11 | `training` | Manhours of training in learning ecosystem led by Nalanda Academy | Total training hours of full-time employees |
| 12 | `Others` | printed: As on 30th June 2024 51 No. of Rooms '000 | printed: Q1 2.5% % Addition (Net) in Q1 |
| 13 | `derivatives` | Foreign currency forward contracts designated as cash flow hedges (USD, GBP, SEK, JPY, EURO forecast purchases | Foreign currency forward contracts designated as cash flow hedges for USD, GBP, SEK, EURO forecast purchases |
| 14 | `compliance` | Sexual harassment complaints: none pending at commencement of year; one complaint received and resolved by ICC | Full compliance with Maternity Benefit Act, 1961 during the year |
| 15 | `hedging` | No outstanding forward contract and no unhedged foreign currency exposure at year end | FX forward contracts designated as cash flow hedges - assets |
| 16 | `water` | Specific water consumption | Specific water consumption |
| 17 | `operational` | Cement sales volume | Cement sales volume |
| 18 | `sustainability` | Aspiration to become carbon negative by 2040; founding member of LEADIT | Renewable Energy Share FY 2025-26 |
| 19 | `Total` | printed: 2,37,500 MTPA | printed: FY20 2,33,000 |
| 20 | `foreign_exchange` | Foreign exchange earnings | Foreign exchange earnings |
| 21 | `capital_commitment` | Estimated amount of contracts remaining to be executed on capital account and not provided for (net of advance | Phase II expansion strategic investments |
| 22 | `caro` | Statement on matters specified in paragraphs 3 and 4 of CARO 2020 given in Annexure I; references paragraph 16 | Company does not hold any inventory |
| 23 | `waste` | Plastic waste generated | Plastic waste generated |
| 24 | `fair_value_hierarchy` | Fair value of borrowings (including current maturity of long term borrowings) - Level 2 | Fair value of borrowings (including current maturity of long term borrowings) - Level 2 |
| 25 | `AUM` | AUM grew 18% year-on-year to Rs. 38,993 crores. | reached a number of Rs. 38,993 crores. |
| 26 | `emissions` | Scope 1 emissions intensity reduction achieved | Scope 2 emissions intensity reduction achieved |
| 27 | `industry` | India per capita cement consumption | Global average per capita cement consumption |
| 28 | `capital_commitments` | Estimated amount of contracts remaining to be executed on capital account and not provided for, net of advance | Estimated amount of contracts remaining to be executed on capital account and not provided for (net of advance |
| 29 | `corporate_action` | Interim dividend already paid per equity share | Final dividend declared per equity share for FY ended March 31, 2026 |
| 30 | `liquidity` | CD ratio declined to 77% from 92% due to strategic excess liquidity | Undrawn committed borrowing facilities available to the Group |
| 31 | `exceptional_items` | Exceptional item - incremental New Labour Code impact on gratuity and other employee benefits | Exceptional loss - impact of new labour code on gratuity and employee benefits |
| 32 | `macro` | India real GDP growth projection (Second Advance Estimates, NSO) | Index of Eight Core Industries (ICI) level |
| 33 | `complaints` | Working Conditions complaints filed by employees and workers | Working Conditions complaints filed by employees and workers |
| 34 | `goodwill` | Goodwill on amalgamation of Adhunik Cement Limited (ACL) with DCBL under NCLT-approved scheme — carrying value | Goodwill on amalgamation of Dalmia DSP Limited with DCBL under NCLT-approved scheme — carrying value as on Mar |
| 35 | `fleet` | Number of plants | States served |
| 36 | `-` | printed: 43 | printed: 9 |
| 37 | `capital` | Paid-up capital of listed entity | Total CapEx (financial capital input) |
| 38 | `fx_exposure` | Net exposure to foreign currency risk (all currencies) | Net exposure to foreign currency risk (all currencies) |
| 39 | `corporate` | Dalmia Bharat is India's fourth-largest cement manufacturer by installed capacity | Corporate Identity Number (CIN) |
| 40 | `esg` | Improvement rate in carbon emission | Total Scope 1 and Scope 2 emissions per rupee of turnover |
| 41 | `17` | printed: 17 | printed: 17 |
| 42 | `exceptional_item` | Exceptional items (net) - standalone | Exceptional items (net) - consolidated |
| 43 | `foreign_currency_exposure` | USD Assets: Trade receivables | USD Assets: Advance to suppliers |
| 44 | `capital_structure` | No bonus shares, shares for consideration other than cash, or buybacks during the five years preceding March 3 | Outstanding GDRs/ADRs/Warrants/Convertible Instruments as on March 31, 2025 |
| 45 | `listing` | Dalmia Cement (Bharat) Limited Non-Convertible Debentures listed on BSE Limited | No outstanding GDRs, ADRs, warrants or convertible instruments as on March 31, 2026 |
| 46 | `procurement` | Year-on-year reduction in procurement costs of MRO and indirect spend | Share of total imported MRO procurement spend directed towards local suppliers |
| 47 | `market` | India cement demand CAGR projection | Global (ex-China) addressable market for wireless and wireline products estimated to grow from US$47 billion t |
| 48 | `human_rights_training` | Permanent employees human rights training (total 4,435; covered 4,447) | Permanent employees human rights training (total 4,317; covered 3,887) |
| 49 | `certification` | Plants with ISO 14001 certification (1 new plant under process) | Plants with EnMS 50001 certification |
| 50 | `energy_consumption` | Total electricity consumption from non-fossil fuel-based grid, WHRS and solar | Total electricity consumption from non-fossil fuel-based grid, WHRS and solar |
| 51 | `discontinued_operations` | Net loss for the year from discontinued operations - consolidated | Loss from discontinued operations |
| 52 | `derivative` | Foreign currency forward contracts designated as cash flow hedges (fair value through OCI) | Interest rate swap contract carried at fair value through profit or loss (March 31, 2020: ₹2 crore) |
| 53 | `1` | printed: Pears 1 सिलेक्टेड डेड 1 साल से | printed: Dove 1 (not explicitly numbered, but visible in text/image as '1' or '100%') |
| 54 | `fx_sensitivity` | Effect on profit before tax of +5% USD change | Effect on profit before tax of -5% USD change |
| 55 | `sensitivity` | Interest rate +50 BPS effect on profit before tax (INR floating borrowings) | Interest rate -50 BPS effect on profit before tax (INR floating borrowings) |
| 56 | `Area Booked` | printed: Q3 FY22 4.21 Lakhs Sq. ft. | printed: Q2 FY23 4.90 Lakhs Sq. ft. |
| 57 | `project` | FGD installation underway at Renusagar plant | Regenerative Thermal Oxidizer with heat recovery at Nachterstedt Rolling Plant for CO reduction |
| 58 | `foreign exchange` | Foreign Exchange Earnings | Foreign Exchange Earnings |
| 59 | `litigation` | Dispute between DCBL and Bawri Group under shareholders agreement dated 16 January 2012; Delhi High Court judg | Matter pertaining to building in which the property is situated is sub-judice before the Hon'ble Supreme Court |
| 60 | `industry_data` | Annual installed cement capacity of India | Cement industry capacity utilisation |

## 13. Proposed files and approval checklist

- `tasks/arch_v4/label_promotion_proposal.json` — new labels (with Beam definitions), aliases to existing labels, buckets, meaningless, unanswered. `applied: false`.
- Opus/Shivam: approve or reject each new label id and assign its parent family; approve aliases; treat `bucket` as an extractor fix, not a vocabulary label; leave `meaningless` as `other:<raw>`.
- To apply after approval (controller, outside this sandbox): rebuild the pilot vocabulary with the fixed `build_vocab` (new ratio/spelling rules are code), then apply only the approved new labels/aliases to `map`; do not delete surfaces. Re-run this review against the installed store to measure the real before/after. The source mount is read-only here; nothing was installed.
