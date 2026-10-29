# NID triage — every `not_in_data` case, 30 Oct 2026

Rule under test (Shivam, 30 Oct 2026): **“not in data” is not an acceptable answer by itself.**
Input: the 150 NID cases of the v4 registry (`tasks/arch_v4/concept_registry.json`, v4.1; 897 mapped /
150 NID / 26 unmapped, reproduced exactly in memory by `build_concept_registry.build()`).
Output: `tasks/arch_v4/nid_triage.json` — one class and one verdict per case.

## Headline

| verdict | cases | share | meaning |
|---|---:|---:|---|
| **a — fetch/held** | **74** | 49.3% | the atom is already held or fetchable free in ≤1 day; the answer is a fact, computation or screen |
| **b — proxy** | **74** | 49.3% | the atom is not published; a formula/proxy over held atoms answers it, with a stated assumption |
| **c — absent** | **2** | 1.3% | neither works |
| total | 150 | 100% | 31 classes · 121 build-hours (62 a + 59 b) · ~9 h of that is network fetch, the rest is readers/formulas over held data |

The single biggest finding: **48 of the 150 are pure concept-map/wiring gaps** over stores we already
hold (adjusted prices, event windows, NPA, CFO, CWIP, loans, F&O OI, held corporate-action subject
text, measured backtests, FCF coverage). Counting the document-reader classes as well, **73 of 150
are answerable from data already on disk** — no new feed. The cheapest four classes (net_npa, cfo,
cwip, loans_book — 17 cases) need **six rows in `xbrl_concept_map`** plus a rebuild, about 4 hours.
Another 16 cases (adjusted prices, event windows) are pure planner wiring. Only three classes need
any new network fetch (scheme/buyback attachments, ~20 monthly business-update PDFs, promoter-pledge
XBRL — about 9 h of the 121).

## Method

- Cases and registry reasons come from the registry itself, not from this document: the generator
  re-ran the v4 builder and asserted `set(case) == set(NID)` before writing.
- Grouped by **true missing atom and ask shape**, not by registry reason. Where the registry reason
  and the question disagree, the JSON keeps `registry_reason` next to the class and §6 lists the
  mis-maps. One case, one class.
- Verdict rule: **a** = held or free-fetchable; **b** = not published, proxy formula needed; **c** =
  neither. A case can be unlocked by an (a) atom and still need a labelled view — the verdict is about
  the data, not the reasoning layer.
- `catalog`, read-only SQL and the pilot stores were read; no DB on `D:` was opened. The task list of
  runners (`D:\RealityEngine\raw\runners`) was listed, not run.

**Network caveat.** This sandbox has no outbound network (`web_search` has no API key; TLS fetches
fail). A source is marked verified when the exact feed is already held (rows in our stores) or the
URL is a live constant in an existing fetcher. No live HEAD check was possible; the URLs below are
the ones the existing fetchers call. The controller should HEAD-check the six URL families once on a
networked box before starting the fetch jobs.

## Plan, sorted by cases unlocked per hour

| # | class | verdict | cases | build h | cases/h | target / source |
|---:|---|---:|---:|---:|---:|---|
| 1 | `adj_price_series` | a | 10 | 1.0 | **10.00** | held `px_nse_adj`/`px_bse_adj`; registry atom only |
| 2 | `event_window` | a | 6 | 1.0 | **6.00** | `event_day0` (3.0M) + daily bars → `event_leakage_window` |
| 3 | `net_npa` | a | 11 | 3.0 | **3.67** | XBRL `PercentageOfNpa` → `company_metric_series` |
| 4 | `cfo` | a | 3 | 1.0 | **3.00** | XBRL `CashFlowsFromUsedInOperatingActivities` |
| 5 | `bank_transmission` | b | 21 | 8.0 | **2.62** | NIM/credit-cost formula over held XBRL |
| 6 | `corp_action_terms` | a | 10 | 4.0 | 2.50 | held NSE corporate-actions subject text |
| 7 | `cwip` | a | 2 | 1.0 | 2.00 | XBRL `CapitalWorkInProgress` |
| 8 | `fno_oi` | a | 1 | 0.5 | 2.00 | held `fno_oi_daily` (16.2M rows) |
| 9 | `mechanism_lag` | b | 17 | 10.0 | 1.70 | 22 World Bank series + `policy_events` + metrics |
| 10 | `free_float_weight` | b | 6 | 4.0 | 1.50 | shares × (1−promoter) / index float mcap |
| 11 | `hfc_securitisation` | b | 9 | 6.0 | 1.50 | securitisation income/assigned loans + NPA guard |
| 12 | `jv_terms` | a | 5 | 4.0 | 1.25 | BSE announcements + concall + deck |
| 13 | `valuation_judgement` | b | 11 | 10.0 | 1.10 | PB/ROE, payout, FCF arithmetic + guidance |
| 14 | `backtest` | a | 3 | 3.0 | 1.00 | daily bars + delivery, walk-forward |
| 15 | `float_income` | b | 2 | 2.0 | 1.00 | client funding book × short rate |
| 16 | `retail_mtm` | b | 1 | 1.0 | 1.00 | public % × shares × Δprice (upper bound) |
| 17 | `corp_action_schemes` | a | 7 | 8.0 | 0.88 | BSE announcement attachments (6,621 held) |
| 18 | `capex_project` | a | 3 | 4.0 | 0.75 | concall/deck dated statements |
| 19 | `guidance_vs_actual` | a | 2 | 3.0 | 0.67 | concall guidance vs reported actuals |
| 20 | `related_party` | a | 2 | 3.0 | 0.67 | `ar_facts` related-party facts (575k) |
| 21 | `dividend_coverage` | a | 1 | 2.0 | 0.50 | FCF = CFO − capex vs dividends paid |
| 22 | `kmp_churn` | a | 1 | 2.0 | 0.50 | announcement headline regex |
| 23 | `loans_book` | a | 1 | 2.0 | 0.50 | XBRL `Advances` + AR/concall loans |
| 24 | `second_order_suppliers` | b | 4 | 8.0 | 0.50 | curated supply edges, filing-named |
| 25 | `unit_metrics` | a | 3 | 6.0 | 0.50 | concall items + deck facts + monthly updates |
| 26 | `policy_incidence` | b | 2 | 6.0 | 0.33 | input-cost shares over `policy_events` |
| 27 | `debt_maturity` | a | 1 | 3.5 | 0.29 | AR borrowings-maturity note |
| 28 | `forecast_scenario` | b | 1 | 4.0 | 0.25 | scenario arithmetic, no target price |
| 29 | `order_book` | a | 1 | 4.0 | 0.25 | order-win announcements + `order_alert` |
| 30 | `promoter_pledge` | a | 1 | 6.0 | 0.17 | SHP XBRL fetch/parse (0 of 49,126 populated) |
| 31 | `refurbished_sales` | c | 2 | 0.0 | n/a | no series exists |

**Top 5 by cases/hour:** `adj_price_series` 10.00 · `event_window` 6.00 · `net_npa` 3.67 ·
`cfo` 3.00 · `bank_transmission` 2.62.

**Cumulative execution order.** Wave 0 (2 h): #1–#2 → 16 cases. Wave 1 (7 h, six concept-map rows):
#3,#4,#7,#23 → 33 cases total. Wave 2 (12.5 h, held-feed parsers): #6,#8,#17 → 51. Wave 3 (28 h,
formulas/readers): #5,#9,#10,#11 → 104. Wave 4 (71.5 h, long tail + the two c-only cases): 150.

## (a) classes — source, format, history, PIT column, target

Every row below has a real URL; “verified” means the feed is already held (we have its rows) or the
URL is the live constant in the fetcher named.

| class | cases | source URL | format | history | PIT column | target table/atom | h |
|---|---:|---|---|---|---|---|---:|
| `adj_price_series` | 10 | `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_04062024.csv` | daily bhavcopy → adjusted OHLC + factors | 2019-01-01..2026-10-19 (4.3M NSE, 6.8M BSE) | `date`; snapshot built 2026-10-19 | atom `price.adj_close` + `price.cagr_adj` | 1 |
| `event_window` | 6 | `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_04062024.csv` | daily OHLCV + delivery, `event_day0` offsets | 2019-01-01..2026-10-19 | `known_at`; `session_0` | `market_state.event_leakage_window` | 1 |
| `net_npa` | 11 | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_BANKING_1696123_18072026040126_WEB.xml` | XBRL → long facts; `PercentageOfNpa` is a fraction ×100 | 2018-12-31..2026-09-30; 31,614 filings | `filings.filing_ts` | `net_npa` / `gross_npa` in `company_metric_series` | 3 |
| `cfo` | 3 | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1690003_09072026063612_WEB.xml` | XBRL cash-flow statement (`FourD` = YTD) | 2018-12-31..2026-09-30 | `filings.filing_ts` | `cfo` | 1 |
| `cwip` | 2 | same INDAS XBRL | XBRL balance-sheet instant (`OneI`) | 2018-12-31..2026-09-30 | `filings.filing_ts` | `cwip` | 1 |
| `loans_book` | 1 | same banking XBRL + `ar_facts`/`concall_facts` | `Advances` instant; “loans/AUM” facts with quote | 2018..2026 | `filing_ts` / `known_at` | `loans` | 2 |
| `corp_action_terms` | 10 | `https://www.nseindia.com/api/corporates-corporateActions?index=equities` | JSON `subject` text (“Interim Dividend - Rs 1.15 Per Share”) | 2019-01-03..2026-10-23; 10,907 dividend rows | `broadcast_date`; `ex_date`/`rec_date` | `market_state.corporate_action_class(amount_per_share, ratio)` | 4 |
| `corp_action_schemes` | 7 | `https://www.bseindia.com/xml-data/corpfiling/AttachHis/7dc128e7-8fd8-475c-b9ed-11fe16e49cc3.pdf` | PDF announcements + `ann` metadata; MERGER/DEMERGER/BUYBACK/RIGHTS rows | 2019-12-31..2026-10-19 (1.9M ann; 6,621 PDFs held) | `DissemDT`; `corporate_actions.broadcast_date` | `corporate_action_class` scheme fields + `event_day0` | 8 |
| `jv_terms` | 5 | BSE attachment URL above | Reg-30 announcements + concall + deck | 2019..2026 | `DissemDT` / `known_at` | `metric_state.entity_relations` | 4 |
| `capex_project` | 3 | BSE attachment URL above | dated capex statements (amount, site, commissioning) | 2016..2026 | `known_at` | `metric_state.capex_project` | 4 |
| `related_party` | 2 | BSE attachment URL above (AR notes) | counterparty + amount + quote | 2015-03-31..2026-03-31 | `ar_docs.filed_at` | `metric_state.related_party` | 3 |
| `kmp_churn` | 1 | BSE attachment URL above | headline regex (CFO appointment/resignation) | 2019-12-31..2026-10-19 | `DissemDT` | `metric_state.company_kmp` | 2 |
| `unit_metrics` | 3 | BSE attachment URL above | structured item/value/unit + monthly updates | 2016..2026 | `known_at` | `metric_state.company_operating_metrics` | 6 |
| `backtest` | 3 | NSE bhavcopy URL above | daily close/delivery + forward returns | 2019..2026 | `date` | `validation_harness` output | 3 |
| `order_book` | 1 | BSE attachment URL above | order-win announcements (customer/value/period) | 2019..2026 | `DissemDT` | `metric_state.order_book_contract` | 4 |
| `guidance_vs_actual` | 2 | BSE attachment URL above (concall) | guidance value/period/firmness vs actual | 2016..2026 | `cc_docs` filing time | `metric_state.guidance_vs_actual` | 3 |
| `debt_maturity` | 1 | BSE attachment URL above (AR note) | maturity buckets with secured split | 2015..2026 | `ar_docs.filed_at` | `metric_state.company_debt_mix` | 3.5 |
| `dividend_coverage` | 1 | same INDAS XBRL | CFO, PPE purchase, dividends paid | 2018..2026 | `filing_ts` | formula `fcf/dividends` | 2 |
| `fno_oi` | 1 | `https://nsearchives.nseindia.com/content/fo/` (fetcher `fetch_fo_bhavcopy.py`) | daily F&O bhavcopy (OI, change, volume, settle) | held (16.2M rows); resumable | `date` | `market_state_b.fno_oi_daily` | 0.5 |
| `promoter_pledge` | 1 | `https://www.nseindia.com/api/corporate-share-holdings-master?index=equities` (fetcher `fetch_shareholding.py --xbrl --parse`) | SHP XBRL, category-level facts | 2015-12-31..2026-10-16 (50,838 filings; only 40 parsed) | `broadcast_at` | `company_ownership_pit.pledge_pct` | 6 |

Verified spot values used in the class notes: `BANKBARODA` Q1FY27 `PercentageOfNpa` 0.005 → **0.50 %**;
`HDFCBANK` Q2FY27 0.0037 → **0.37 %**; `AUBANK` 0.0076 → **0.76 %**. `HDFCBANK` Q2FY27 `CashFlowsFromUsedInOperatingActivities`
and `CapitalWorkInProgress` exist in the TCS/HDFC filings sampled; `TCS` has both concepts in its
2026-06-30 filing. `corporate_actions`: 10,572 of 10,907 dividend rows carry “Per Share”; 308/308
splits carry the face-value ratio; 319 bonuses and 234 buybacks do **not** carry terms in the subject
and fall back to the announcement attachment (class 17).

## (b) classes — proxy recipe, assumption, confidence, worked example

### B1. `bank_transmission` — 21 cases (MB0472 … MB0985)
- **Recipe.** `NIM_q = (InterestEarned_q − InterestExpended_q) / avg(Advances + Investments) × 4`;
  `credit_cost_q = ProvisionsOtherThanTaxAndContingencies_q / avg(Advances)`; deposit repricing from
  the AR deposit schedule (savings/term); repricing order (EBLR → MCLR → fixed) from the AR/deck.
- **Assumption.** Quarter-end balances approximate averages; disclosed NIM includes CRR/SLR and other
  earning assets, so the computed series is a proxy, not the reported number.
- **Confidence.** Medium-high (NIM within ~10–15 % of reported; credit cost medium).
- **Worked example (MB0931, HDFC Bank Q2FY27).** `InterestEarned_q` 83,427 cr − `InterestExpended_q`
  48,807 cr = **NII 34,619 cr**; earning assets = Advances 33.16 lakh cr + Investments 13.57 lakh cr
  = **46.73 lakh cr**; NIM = 34,619/4,673,000 × 4 = **2.96 % annualised** on quarter-end balances.
  The one-off leg is `RevenueOnInvestments` vs `OtherIncome` in the same filing: if the treasury
  delta is more than half the NIM delta, the answer says the expansion is one-off.

### B2. `mechanism_lag` — 17 cases (MB0356 … MB0921)
- **Recipe.** For each hop, cross-correlate the held monthly series (World Bank Pink Sheet:
  `wb_gold`, `wb_rubber`, `wb_crude_brent`, `wb_urea`, `wb_natgas_*`, `wb_coal_*`, `wb_cotton_a`,
  `wb_dap`, `wb_iron_ore` — 22 series, 7,062 observations, to 2026-09-30) against the company metric
  at lags 0–4 quarters. Report the lag with max |correlation| and its sample size. The hop with no
  held series is stated as an assumption, not measured.
- **Assumption.** Monthly commodity averages map to the quarter they fall in; policy dates are
  `policy_events.effective_date`; unmeasured hops are labelled.
- **Confidence.** Medium-low (direction often clear, magnitude and lag usually not).
- **Worked example (MB0460, gold 2,028 → 4,186.7, 7 Aug 2020 to 30 Sep 2026).** TITAN adjusted close
  1,091.05 → 4,587 (**+320 %, 26.3 % CAGR**); MUTHOOTFIN 1,217 → 2,737.1 (**+125 %, 14.1 % CAGR**).
  Price says the **jeweller** won, not the gold-loan NBFC; the answer names the channel (gold →
  jewellery revenue vs gold → LTV/AUM) and says gold alone explains neither.

### B3. `hfc_securitisation` — 9 cases (MB0012, MB0141–MB0148)
- **Recipe.** `securitised_share = securitisation_income / (securitisation_income + interest_income)`
  from the AR note, or “loans assigned” / disbursements from the PPT; rank HFCs by it; guard =
  Δ net NPA ≤ 2 pp from `results_xbrl.PercentageOfNpa`.
- **Assumption.** Securitisation income is proportional to the securitised book (same yield across
  HFCs).
- **Confidence.** Medium-low (income-to-book is an imperfect proxy for disbursement share).
- **Worked example (MB0141, Can Fin Homes Q1FY27).** The net-NPA leg is exact from XBRL; the
  securitised share is read from the Q1FY27 investor presentation (held deck, securitisation slide).
  Answer form: “Can Fin net NPA x % (filing f); securitised share y % of disbursements (PPT p.n);
  guard passes/fails by z pp”, with the share labelled an estimate. The deck text search currently
  finds no securitisation passage, so this needs a targeted page extraction first.

### B4. `free_float_weight` — 6 cases (MB0660, MB0733, MB0738, MB0744, MB0848, MB0926)
- **Recipe.** `free_float = shares_out × (1 − promoter_pct/100)`; `float_mcap = free_float × close`;
  `weight_i = float_mcap_i / Σ float_mcap` over the index members at that date
  (`company_membership_pit` 10,895 rows / 133 indices, added_on/removed_on). A promoter sale of k pp
  multiplies the weight by `(100 − P + k)/(100 − P)`.
- **Assumption.** Float-weighted index, no capping band; promoter % at the last quarter-end.
- **Confidence.** High for free float and direction, medium for the absolute weight.
- **Worked example (MB0738, promoter OFS of 8 %).** MUTHOOTFIN promoter 73.35 %, public 26.65 %
  (2026-06-30). After an 8 pp OFS: float 26.65 % → 34.65 %, a **1.30×** relative increase; a
  float-weighted weight rises ~1.30× before capping. The price reaction is a flow question the data
  cannot separate from the sale's information content.

### B5. `float_income` — 2 cases (MB0483, MB0568)
- **Recipe.** `float_income ≈ average client funding book × 91-day T-bill yield`; client funding book
  from the AR note (“client funding” / “balances with clearing corporation”); cross-check interest
  income; give a range.
- **Assumption.** Client float is invested at the short rate and the book is stable through the quarter.
- **Confidence.** Low-medium — management refuses the split.
- **Worked example (MB0483, Angel One).** 2023-04-21 transcript p.25, Vineet Agrawal: *“We are not
  disclosing the breakup of the float income and the interest income, which we earn from client
  funding book yet.”* So the share is a proxy; the answer must label it an estimate.

### B6. `second_order_suppliers` — 4 cases (MB0512, MB0518, MB0523, MB0868)
- **Recipe.** Curated edge `supplier → customer/segment` from AR related-party and customer-
  concentration notes + order announcements naming the buyer. Evidence bar = a filing that names the
  relationship; size only where an order value is filed.
- **Assumption.** A named relationship implies revenue exposure; unlisted intermediaries are skipped.
- **Confidence.** Medium for who is in the chain, low for the size.
- **Worked example (MB0512, BEL/HAL indigenisation).** The second layer contains only names with a
  filing naming a defence programme or PSU customer (e.g. “receipt of order from BEL”). The answer
  lists names with filing date and order value, and says which links are inferred from sector
  membership rather than a named order.

### B7. `policy_incidence` — 2 cases (MB0513, MB0608)
- **Recipe.** First hit = companies whose cost-of-materials line contains the taxed input (cogs split
  from `company_cost_structure`); second = their customers by sector input share; the policy row from
  `policy_events` with `effective_date` and amount.
- **Assumption.** Input-cost shares are the transmission weights; no firm-level pass-through.
- **Confidence.** Medium-low.
- **Worked example (MB0513, TCS on coal/iron-ore doubles to 2 % from 1 Apr 2026).** First hit =
  coal/iron-ore producers and steel/cement (coal is in cogs); second = power and steel users. The
  answer names the `policy_events` row and labels the second layer an input-share estimate.

### B8. `valuation_judgement` — 11 cases (MB0877, MB0888, MB0935, MB0939, MB0959, MB0965, MB1005, MB1010, MB1011, MB1013, MB1028)
- **Recipe.** State the arithmetic: `g_implied` from `PB = (ROE − g)/(r − g)` with r = 12 % and ROE =
  3-year average; `payout = (CFO − capex)/dividends`; premium to book = PB vs ROE; compare with the
  company's own guidance (`concall_facts`) and delivered trend, **not consensus**.
- **Assumption.** Cost of equity 12 %; sustainable ROE from the 3-year average; no analyst consensus
  (Shivam 2026-10-19: consensus is a guess, use guidance).
- **Confidence.** Low-medium — a labelled view, never a “fair value”.
- **Worked example (MB1010, Power Grid).** `payout = regulated equity × allowed RoE × (1 − capex share
  of regulated equity)`. If the capex cycle slows, regulated-equity growth slows and the same RoE
  supports a higher payout mechanically. Give the payout range at the last five years' capex intensity
  and label the regulated-return assumption.

### B9. `forecast_scenario` — 1 case (MB0627)
- **Recipe.** Show the arithmetic of a doubling: a mid-cap at 20× with 18 % earnings growth needs
  ~40×, or a 100 % earnings beat, in 12 months. Give a range and the assumptions, never a single name
  as a fact.
- **Assumption.** Multiple and earnings paths are scenarios, not predictions.
- **Confidence.** Low, by construction.
- **Worked example (MB0627, “which mid-cap will double in 2027?”).** Answer with the two paths
  (re-rating vs earnings) and the screen that produces candidates; any single name is a scenario.
  SCHEMA_FINAL §4 marks this kind as NOT IN DATA with a labelled view.

### B10. `retail_mtm` — 1 case (MB0629)
- **Recipe.** `retail_loss = Σ_ISIN (public_pct − fii_pct − dii_pct) × shares_out × Δprice`; where
  FII/DII are null, use `public_pct` and report an **upper bound**.
- **Assumption.** Quarter-end ownership applied to that day's price change; public % includes
  institutions when the split is missing.
- **Confidence.** Low-medium (upper bound).
- **Worked example (4 Jun 2024).** Public (non-promoter) holding value = **Rs 8.99 lakh crore** across
  1,724 matched ISINs (`company_state_daily` × `company_ownership_pit`); Nifty −5.9 % → upper bound
  ≈ **Rs 53,000 crore**. The answer says it is an upper bound, not a measured retail loss.

## (c) absent — 2 cases

| case | question | what was tried | why it fails |
|---|---|---|---|
| MB0195 | why did second-hand/refurbished electronics demand rise in CY2026; who benefits; structural or cyclical; state the data gap | BSE announcement headlines, investor decks, concalls; checked for an exchange/industry-body series | no listed company or exchange publishes a refurbished-sales series; GfK/Counterpoint are paid and do not cover India refurbished retail; import data is not held and would not give refurbished retail sales |
| MB0200 | what do our stores say about refurbished sales in CY2026 | same stores | no sales series exists to quote; the rubric accepts the NID statement naming the missing store (SCHEMA_FINAL §4) |

Note: the other SCHEMA_FINAL “NOT IN DATA” families are **not** in this NID set (they were answered
as class-a statements), and “investor-level holdings” is now a **proxy**, not absent.

## What the registry got wrong

These are registry defects, not data gaps; fixing them changes the denominator, not the data:

1. **12 cases tagged “NSE publishes no free retro intraday bars”; none needs intraday.** Every one is
   a session-window or chain question answerable from daily OHLCV/delivery (Shivam 2026-10-29:
   intraday is not needed).
2. **40 cases tagged `corporate_action_class.amount_per_share`**: 10 are adjusted-price/return
   questions already answerable from held adjusted prices; 10 are dividend/bonus/split terms (held
   subject text); 7 are scheme/buyback terms (held announcements); 13 need other atoms (debt
   maturity, pledge, related party).
3. **`net_npa` 21 → 11**: 9 are HFC securitisation questions with an NPA guard; 1 (MB0761) is capex
   commissioning slippage.
4. **“investor-level holdings are not published”** → aggregate public % *is* published, so MB0629 is
   a proxy (b), not absent.
5. **“private transaction terms are never filed”** (MB0999) is a second reason on a CFO/DSO question;
   no private-terms atom is needed.
6. **“investments” (8 cases)** are mostly JV/subsidiary questions, not the balance-sheet Investments
   line; only MB1005 is a portfolio-NAV question.
7. **“loans” (15 cases)** are mostly rate-transmission/mechanism questions; exactly one (MB0962) is a
   loan-book lookup.
8. **MB0655/MB0671/MB0677** cite `company_metric_series.value` as missing, but the table holds
   1,056,589 rows over 21 metric keys; the gap is metric keys (`nim`, `loans`, `credit_cost`), not
   the table.
9. **Six “absent” atoms are not absent**: adjusted prices, event windows, F&O OI, pledge (fetchable)
   and the six XBRL bank concepts are held or one concept-map row away.

## Verification

```text
python -c "import json;d=json.load(open('tasks/arch_v4/nid_triage.json'));print(len(d['cases']), {v:sum(c['verdict']==v for c in d['cases']) for v in 'abc'})"
150 {'a': 74, 'b': 74, 'c': 2}
```

The generator asserted `set(cases) == set(NID)` against the in-memory v4 rebuild (897/150/26), that
each of the 150 has exactly one class, that every (a) class has a source URL, and that every (b)
class has a recipe and a worked example. All reads were read-only; no DB on `D:` was opened; no fetch
was run.
