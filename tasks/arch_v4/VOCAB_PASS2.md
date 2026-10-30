# VOCAB_PASS2 — the head surfaces labelled by free Beam

Generated 2026-10-30T23:16:46+00:00 by `python -m reality_engine.query.v4.map_vocab_beam`; model `beam-free` (free) on OpenCode Go. The store is `.tmp/v4_vocab_pass2.db`, a copy of the WP2b vocabulary with `map.source` (deterministic | beam) on every row.

**Install (controller):** back up the pilot store, then copy this file over `reality_engine/data/pilot/v4/v4_vocab.db`. Everything downstream reads `map`, which keeps its old values for deterministic rows and carries the Beam answer plus `source='beam'` for the rest. No other table changed shape except the one added column.

## 1. The gate (§A.9 option b)

| measured | value |
|---|---:|
| head surfaces (the declared 95% of occurrences) | 62,601 |
| named by the deterministic pass | 37,204 (59.43%) |
| sent to Beam (this pass) | 25,397 |
| Beam answered with an exact label | 6,540 (25.75% of the workload) |
| Beam answered `other:<raw>` | 18,857 (74.25%) |
| **head surfaces carrying an exact label** | **43,744 / 62,601 = 69.88%** |
| gate (>= 95% exact labels) | **NOT MET** |
| workload share of occurrences | 27.38% |
| workload **occurrences** now carrying an exact label | 21.31% |

Head membership note: sorting the store by occurrences puts the 95% cut inside the 22,782 surfaces that occur exactly twice, so which of them are "in the head" is a tie-break artefact. `unmapped_head.json` (the WP2b dump this pass consumes) puts **all 7,430 unmapped twice-occurring surfaces** in the head and fills the rest with labelled ones, which is the largest workload and gives the 62,601 / 37,204 / 25,397 split in the brief. A different tie order gives the same 62,601 total and the same gate arithmetic, because the surfaces it swaps are already labelled. `1,815,581` occurrences is the corrected figure (`VOCAB_PASS1.md` §1, corrected here).

The `other:<raw>` share per document type inside the workload:

| document type | Beam `other` share |
|---|---:|
| annual_report | 78.80% |
| concall | 54.21% |
| deck | 73.57% |

## 1b. Why the head gate is not met — what the `other` surfaces actually are

The dataset's most frequent unmapped surfaces are not metrics at all; they are extractor buckets and section headings, so `other` is the correct answer:

| surface | occurrences | document type |
|---|---:|---|
| `signal` | 39,143 | annual_report |
| `market_data` | 4,156 | annual_report |
| `ratio` | 4,118 | annual_report |
| `operations` | 2,708 | annual_report |
| `environment` | 2,546 | annual_report |
| `energy` | 2,335 | annual_report |
| `credit_rating` | 2,291 | annual_report |
| `environmental` | 2,232 | annual_report |
| `safety` | 2,227 | annual_report |
| `balance_sheet` | 2,133 | annual_report |
| `derivatives` | 2,043 | annual_report |
| `fair_value` | 2,015 | annual_report |
| `training` | 1,998 | annual_report |
| `AUM` | 1,893 | annual_report |
| `operational` | 1,890 | annual_report |
| `hedging` | 1,890 | annual_report |
| `balance sheet` | 1,860 | annual_report |
| `Others` | 1,839 | deck |
| `Area Booked` | 1,815 | deck |
| `water` | 1,795 | annual_report |

To reach 95% of the 62,601 head surfaces, 15,727 of the 18,857 remaining `other` surfaces would each have to take a declared label. They are, by document type, annual-report/BRSR section headings (`Company Profile`, `Data breach`, `ESG-climate`, `NGRBC principle-wise performance`), presentation line labels (`Area Booked`, `Others`, `Aerial View`) and extractor buckets (`signal`, `market_data`, `ratio`). No declared topic names them, so the fix is vocabulary **promotion**, not a better mapper: the promotion queue is the `other_cluster` table inherited from the WP2b pass (26,261 clusters, 173 queued at >=20 occurrences / >=3 companies / >=2 doc types), and it has to be re-clustered against this store after install because the `other` set shrank.

## 2. Calls and throughput

| measured | value |
|---|---:|
| batches (round 1 / round 2A / round 2B) | 508 / 10 / 10 |
| surfaces mapped (round 1 / round 2) | 25,397 / 1,000 |
| answers accepted on the first ask | 26,391 / 26,397 |
| first-answer rejects, retried once | 6 |
| tokens in / out | 2,205,839 / 657,673 |
| batch wall time: min / median / max | 5.8 / 464.5 / 2355.2 s |
| sustained throughput, round 1 | 12.4 batches/min |
| 429s (in runs that completed) | 0 |

**How the ceiling was measured.** Concurrency is not fixed: the gate starts at the value passed on the command line, doubles after every 20 clean calls and halves on every 429, never returning to a level that 429'd. What the provider did, measured: it throttled by **slowness first** — the first 100 s ran 57 batches at limit 4 (~34 batches/min, 6 s each), then batch wall time grew to 20-360 s for the same 50 phrases with the same token counts, so the run settled near 10 batches/min and no 429 appeared for 495 batches. It then rate-limited with an HTTP 429 `Upstream request failed: Rate limit exceeded` and one such 429 used to end the run; a 429 now lowers the limit, backs off and retries six times before leaving that batch pending for the next run, so the finish and the agreement round ran with zero 429s at limit 2. The honest ceiling on this account tonight is *not* a concurrency number: it is the provider's queue, and the measured output is thousands of phrases an hour.
Every call is written to `tasks/ledgers/spend.jsonl` at $0 through `cost_ledger.record_usage`.

## 3. Agreement (500 head surfaces mapped twice, different batches)

- pairs with both answers: **500**; identical label: **427** -> **85.40% agreement**
- of those already labelled deterministically (311), Beam's label equals the deterministic label on 202
- read honestly: 14.6% of these surfaces were labelled differently by the same model in a different batch, so a single Beam label on an ambiguous phrase is not reproducible. That is the reason the conservative prompt answers `other` when two labels are defensible.

## 4. The labels Beam used

| label | family | surfaces |
|---|---|---:|
| geography | segments_business | 600 |
| volume | demand_orders | 562 |
| segment | segments_business | 390 |
| capacity | demand_orders | 380 |
| revenue | financial_performance | 328 |
| employee | people_governance | 254 |
| asset | costs_balance_sheet | 237 |
| product | segments_business | 186 |
| cost | costs_balance_sheet | 178 |
| equity | costs_balance_sheet | 172 |
| holding | ownership_market | 136 |
| capacity_utilisation | demand_orders | 132 |
| market_share | demand_orders | 132 |
| receipt | financial_performance | 131 |
| debt | costs_balance_sheet | 115 |
| growth | financial_performance | 115 |
| csr | people_governance | 115 |
| loan | financial_performance | 99 |
| provision | costs_balance_sheet | 98 |
| commodity | policy_macro | 83 |
| customer | segments_business | 82 |
| gross_npa | financial_performance | 81 |
| expansion | demand_orders | 81 |
| material | costs_balance_sheet | 78 |
| net_npa | financial_performance | 78 |
| shareholding | ownership_market | 71 |
| category | segments_business | 64 |
| production | demand_orders | 64 |
| price | ownership_market | 63 |
| subsidy | policy_macro | 55 |

## 5. Hand check

A stratified sample of 100 Beam mappings is in `vocab_pass2_sample.md`. Precision is **not** asserted here; the hand check is the controller's, and the worker's own reading is reported separately in that file.

## 6. Round-2 disagreements (first 40)

Same surface, same model, a different batch: the label changed.

| surface | batch A | batch B |
|---|---|---|
| `Indian commercial vehicles` | segment | other |
| `Quarterly disbursements` | other | loan |
| `pricing` | other | price |
| `Customer complaints` | customer | other |
| `NGRBC complaints` | other | governance |
| `cci_penalty_stay` | other | policy |
| `contract_won` | other | order_intake |
| `cost_audit` | cost | auditor |
| `inventories_pledged` | inventory | pledge |
| `investment_gain` | income | investment |
| `investments_associates` | investment | other |
| `investments_pledged` | pledge | investment |
| `jvs_associates` | jv | other |
| `loan_to_related_party_doubtful` | rpt | loan |
| `pledged_deposits` | deposit | other |
| `product_eco_design` | other | product |
| `segment_da` | other | depreciation |
| `unhedged foreign currency exposure` | risk | other |
| `wage_ratio` | remuneration | employee |
| `3 Year Revenue CAGR` | revenue | growth |
| `Cash from Investments` | cash | cash_flow |
| `Chemicals (A + B + C)` | segment | other |
| `Domestic B2B UVG` | other | volume |
| `GAL Stake (%) – GHIAL, Hyderabad, India` | other | holding |
| `Gold Loans (₹ Crs) - SMA 2` | sma | loan |
| `Great Acres % Saleable Area sold prior to OC (msf)` | volume | other |
| `Gross Profit` | other | pat |
| `Hyderabad Domestic Passenger Traffic growth` | volume | growth |
| `Increased Pipes & Tubes Capacity/Production (MT)` | other | capacity |
| `Initiation Fees` | other | revenue |
| `International Hotels $ - Q2 - Dubai - RevPAR in $` | revenue | other |
| `Investment Multiple 1<1.5 PY-3*` | other | investment |
| `Jaipur Daksh Phase 3 Area Booked` | order | other |
| `Jam Khambhaliya REZ Ph-II (5.5 GW) + Jamnagar Ph-I` | capacity | other |
| `Mutual Fund AUM growth` | other | growth |
| `Net debt / EBITDA` | other | net_debt |
| `PIEM HOTELS LTD Revenue Growth` | revenue | other |
| `Phase II – 5,500MT – Commenced Production in July 2018` | production | commissioning |
| `Profit attributed to shareholders margin` | ebitda_margin | other |
| `Retail Stores - Tier wise - Metros` | other | segment |
