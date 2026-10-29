# SCHEMA FINAL - 2026-10-29

One schema for the 1,073-case master bank (`tasks/master_bank/MASTER_BANK.jsonl`): every case is
either answered by a built table (`a`), closed by one named table/fetch (`b`), or NOT IN DATA with
a reason (`c`). The runnable DDL is `tasks/SCHEMA_FINAL_2026-10-29.sql`; the per-case appendix is
`tasks/SCHEMA_FINAL_CASES_2026-10-29.jsonl` (exactly 1,073 rows).

This file consolidates `tasks/arch_v3/{SCHEMA_V3.sql,CASE_MAP.jsonl,COVERAGE.md,QUERY_LAYER.md,PILOT_SPEC.md,INDEX_MIGRATION_V0.sql,SPEED_PLAN.md}`,
`tasks/arch_v3_chunks/INDEX_SPEC.md`, `tasks/RIPPLE_SCHEMA_REQUIREMENTS_2026-10-28.md`,
`tasks/LABELS_TAGGING_PLAN_2026-10-27.md`, `tasks/QUERY_TEMPLATES_2026-10-27.md`,
`tasks/ARCHITECTURE_OVERHAUL_2026-10-27.md`, the six SSD pilot stores and the live-store DDL.

## Headline

| class | cases | share | meaning |
|---|---:|---:|---|
| **a** answerable from built tables | **629** | 58.6% | 47 live-store tables + the 30 pilot-built tables |
| **b** one named build/fetch away | **435** | 40.5% | 224 table-population/reader, 211 fetch-then-load |
| **c** NOT IN DATA | **9** | 0.8% | 4 reasons, all justified |

After the 224 table-class builds on held data: **853 / 1,073 = 79.5%**.
After the 211 fetch-class builds too: **1,064 / 1,073 = 99.2%**. The remaining 9 are the NID rows.
The 95% pilot gate therefore **requires the fetch stream**: on held data alone the design tops out at
79.5%, which is the honest number and matches `arch_v3/COVERAGE.md` (79.6% on the 1,030-row case map).

**Class `a` means schema-answerable, not currently correct.** The pilot60 hand check found 55 of 60
sampled answers substantively wrong even though the row-count grader called them ANSWERED
(`tasks/pilot60/REPORT.md` §7, precision 5%). The planner needs an entity/relevance gate; that is a
code gap, not a schema gap, and it is called out in §6.

## 1. Principles

1. **ISIN anchor, never today's symbol.** Every table keys on `isin` at the time of the event.
   `market_state.isin_rekey_map` (old,new,effective_on,reason,verified) is the ISIN-history map;
   `RESOLVE` consults it first, then `symbol_isin_history` for the window valid at `as_of`. An ISIN
   can change on a split/face-value change, so history is never rewritten (G0: 83 false changes,
   1,370 synthetic ISINs, 1,665 FY25+ ISINs absent from the master).
2. **PIT rules.** `known_at` is the first instant the market could see the row and comes from the
   filing record: `bse_dissem_ts` > `publication_date` > `filings.dissem_ts` >
   `bse_ann.DissemDT` > letterhead/folder (pit_conf 0.6-0.8). It is never the crawl date
   (`corporate_documents.doc_date`). `known_at_src` says which record it came from; `pit_conf` is
   1.0 exact exchange timestamp, 0.8 date only, 0.6 inferred. The DuckDB snapshot adds
   `known_at_utc` and `known_at_precision`. Every derived table carries `known_at` even when its
   source does not (`mkt_commodity_daily` has none, which is why the series table adds it).
3. **15:30 IST day-0 rule.** A filing after 15:30 IST belongs to the next session:
   `event_day0(known_at, session_0, offset, in_session)` and windows only ever walk backwards from
   `as_of`, so no future session can leak into an answer.
4. **SSD vs HDD.** Live DBs, the pilot copies and the vector index folders live on the SSD under
   `reality_engine/data/`; raw originals (content-addressed by sha256) live on the HDD under
   `D:\RealityEngine\raw` and are audit/replay only. Never read a DB from D:; never put a SQLite
   file on D: (the 3.3M-event and 7.3M-price scans are already near the 2 s budget).
5. **Storage stack.** SQLite-per-domain, one writer per file, WAL: six live stores + three new
   domains (`market_state.db`, `metric_state.db`, `chunks_v3.db`) + a dated, read-only DuckDB
   snapshot (`snapshots/truth_<date>.duckdb`) for research/backtests. Text search is FTS5 inside
   `chunks_v3.db`; dense vectors are NOT in SQLite (3.4M x 4096 f32 = 56 GB) but in a NumPy/FAISS
   index folder per model, bridged by `chunks_v3.chunk_vec_ref(model, chunk_id, row_idx, dim)`.
   PostgreSQL/pgvector is not installed and is not part of this design.
6. **One file, ten schemas for verification.** The SQL `ATTACH`:s ten in-memory domains so the whole
   design parses and is testable in one `executescript`; in production each section is applied to
   its own file. The 10-attach limit of SQLite is exactly met.
7. **"Owner" tables do not proliferate.** Four SCHEMA_V3 tables were merged/reused rather than
   copied: the five external-series tables are now one `series_observation` table plus the five
   nameable views; `macro_series.db` is folded into `market_state.db`; `arch_v3.result_note` is
   `chunks_v3.result_note`; `metric_state.db` is the production name of the pilot `facts_pilot.db`.
   The opinions family needs no `opinions.db`: `chunks_v3.doc.source_class='opinion'` carries it.
---

## 2. Tables by domain

The DDL for every table below exists verbatim in `SCHEMA_FINAL_2026-10-29.sql` (the section per domain is named); this section is the inventory. Status: **live** (built by ingestion), **pilot-built** (built on the SSD pilot copies, 2026-10-29), **designed-only** (DDL in the final SQL, no rows yet), **snapshot** (DuckDB copy, read-only), **view** (computed, not a copy). Rows are measured, `-` = none yet.


### 2.1 `equity_intelligence` (live store)

| table | kind | status | rows | PK | PIT | idx | what |
|---|---|---|---:|---|---|---:|---|
| `annual_financials` | table | live | 12,933 | id | - | 2 | annual P&L/BS summary |
| `board_meetings` | table | live | 120,451 | symbol,meeting_date,purpose,intimated_at | - | 2 | board meeting calendar |
| `bulk_block_deals` | table | live | 271,800 | id | - | 5 | bulk/block deals |
| `circuit_hits` | table | live | 243,049 | date,symbol,series | date | 1 | band-lock days |
| `company_industry` | table | live | 2,055 | isin | - | 0 | industry classification |
| `corporate_actions` | table | live | 18,240 | id | - | 3 | splits/bonus/dividends |
| `corporate_documents` | table | live | 127,253 | id | - | 4 | document registry |
| `daily_price_delivery` | table | live | 3,194,632 | date,symbol | date | 5 | normalised NSE/BSE OHLCV + delivery + SMA/RSI/52w |
| `document_chunks` | table | live | 2,939,096 | chunk_id | - | 7 | v2 chunks (frozen after v3 parity) |
| `etf_inav` | table | live | 6,800 | isin,date | - | 0 | ETF iNAV |
| `etf_master` | table | live | 432 | isin | - | 0 | ETF master |
| `etf_px` | table | live | 315,259 | date,symbol | date | 0 | ETF prices |
| `fund_nav` | table | live | 323,489 | isin,date | - | 0 | MF NAV |
| `geographic_exposure` | table | live | 3,568 | company_id,country_id | - | 0 | undated geo revenue (company_id keyed) |
| `index_membership` | table | live | 300 | - | as_of | 0 | one snapshot 2026-09-30 |
| `index_tri` | table | live | 13,531 | index_name,date | - | 0 | index total-return |
| `insider_trades_v2` | table | live | 333,712 | source_key | known_at | 3 | PIT insider trades |
| `intelligence_fts` | virtual | live | 2,939,096 | - | - | 0 | FTS5 over v2 chunks |
| `macro_events` | table | live | 30 | event_id | event_date | 2 | curated macro events |
| `master_companies` | table | live | 6,940 | isin | - | 2 | equity master, one row per ISIN |
| `mkt_bse_eq_daily` | table | live | 7,527,246 | date,sc_code | date | 2 | BSE bhavcopy (isin 36% filled) |
| `mkt_commodity_daily` | table | live | 25,255 | date,commodity | date | 0 | 13 commodity series, NO known_at |
| `mkt_fii_dii_cash` | table | live | 1,935 | date | date | 0 | FII/DII cash flows |
| `mkt_nsdl_fpi_daily` | table | live | 30,128 | date,asset_class,route | date | 0 | NSDL FPI flows |
| `mkt_nse_full_daily` | table | live | 4,314,909 | date,symbol,series | date | 2 | NSE sec_bhavdata_full |
| `mkt_nse_index_daily` | table | live | 206,437 | date,index_name | date | 0 | NSE index OHLC |
| `nse_index_breadth` | table | live | 5,717 | date,index_name | date | 0 | advance/decline |
| `pib_releases` | table | live | 2,252,000 | prid | - | 1 | PIB press releases |
| `policy_events` | table | live | 21,552 | id | - | 3 | extracted policy claims |
| `price_bands` | table | live | 1,054,354 | date,symbol,series | date | 1 | daily price band |
| `quarterly_financials` | table | live | 15,173 | id | - | 2 | quarterly summary |
| `raw_documents` | table | live | 39,645 | doc_id | - | 6 | raw audit trail |
| `security_master` | table | live | 8,434 | isin | - | 0 | registry incl delisted names |
| `shp_facts` | table | live | 30,509 | file,context,concept | - | 0 | raw SHP XBRL cells |
| `shp_index` | table | live | 50,838 | record_id | quarter_end | 1 | PIT shareholding (live store) |
| `symbol_isin_history` | table | live | 9,360 | exchange,symbol,isin,first_date | - | 2 | symbol<->ISIN windows |

### 2.2 `results_xbrl` (live store)

| table | kind | status | rows | PK | PIT | idx | what |
|---|---|---|---:|---|---|---:|---|
| `facts` | table | live | 13,941,210 | - | - | 4 | long XBRL facts (554 concepts) |
| `filings` | table | live | 106,613 | file | - | 2 | NSE results XBRL filings |

### 2.3 `ar_facts` (live store)

| table | kind | status | rows | PK | PIT | idx | what |
|---|---|---|---:|---|---|---:|---|
| `ar_docs` | table | live | 33,705 | doc_id | - | 0 | annual-report registry |
| `ar_facts` | table | live | 32,443,403 | - | - | 2 | AR extracted facts (33M) |

### 2.4 `deck_figures` (live store)

| table | kind | status | rows | PK | PIT | idx | what |
|---|---|---|---:|---|---|---:|---|
| `deck_sources` | table | live | 26,572 | source,source_id | - | 1 | deck registry |
| `facts` | table | live | 13,600,000 | - | - | 1 | long XBRL facts (554 concepts) |
| `outputs` | table | live | 822,200 | sha256,page_no,prompt_version,model | - | 0 | vision-model page outputs |
| `pages` | table | live | 815,837 | sha256,page_no,prompt_version | known_at | 1 | deck pages |

### 2.5 `concall_facts` (live store)

| table | kind | status | rows | PK | PIT | idx | what |
|---|---|---|---:|---|---|---:|---|
| `cc_docs` | table | live | 9,300 | doc_id | - | 1 | concall registry |
| `cc_items` | table | live | 645,000 | doc_id,list_name,idx | - | 1 | concall items |

### 2.6 `bse_announcements` (live store)

| table | kind | status | rows | PK | PIT | idx | what |
|---|---|---|---:|---|---|---:|---|
| `ann` | table | live | 1,947,087 | NEWSID | - | 0 | BSE announcements |

### 2.7 `truth_duckdb` (DuckDB snapshot)

| table | kind | status | rows | PK | PIT | idx | what |
|---|---|---|---:|---|---|---:|---|
| `ar_docs` | table | snapshot | 33,705 | - | filed_at,known_at_utc | 0 | annual-report registry |
| `ar_facts` | table | snapshot | 32,443,403 | - | filed_at,known_at_utc | 0 | AR extracted facts (33M) |
| `bse_ann` | table | snapshot | - | - | known_at_utc | 0 |  |
| `cc_docs` | table | snapshot | 9,300 | - | filed_at,known_at_utc | 0 | concall registry |
| `cc_items` | table | snapshot | 645,000 | - | filed_at,known_at_utc | 0 | concall items |
| `deck_facts` | table | snapshot | - | - | known_at_utc | 0 |  |
| `deck_pages` | table | snapshot | - | - | known_at_utc | 0 |  |
| `deck_sources` | table | snapshot | 26,572 | - | known_at,known_at_utc | 0 | deck registry |
| `events` | table | snapshot | - | - | known_at_utc | 0 |  |
| `fii_dii_cash` | table | snapshot | - | - | date,known_at_utc | 0 |  |
| `nse_master` | table | snapshot | - | - | - | 0 |  |
| `pib_releases` | table | snapshot | 2,252,000 | - | known_at_utc | 0 | PIB press releases |
| `policy_events` | table | snapshot | 21,552 | - | published_at,known_at_utc | 0 | extracted policy claims |
| `price_bands` | table | snapshot | 1,054,354 | - | date,known_at_utc | 0 | daily price band |
| `px_bse` | table | snapshot | - | - | date | 0 |  |
| `px_bse_adj` | table | snapshot | - | - | date | 0 |  |
| `px_daily` | table | snapshot | - | - | date | 0 |  |
| `px_nse` | table | snapshot | - | - | date | 0 |  |
| `px_nse_adj` | table | snapshot | - | - | date | 0 |  |
| `px_primary_raw` | table | snapshot | - | - | date | 0 |  |
| `results_facts` | table | snapshot | - | - | period_start | 0 |  |
| `results_filings` | table | snapshot | - | - | period_start,dissem_ts,known_at_utc | 0 |  |
| `security_master` | table | snapshot | 8,434 | - | - | 0 | registry incl delisted names |
| `symbol_isin_history` | table | snapshot | 9,360 | - | - | 0 | symbol<->ISIN windows |

### 2.8 `market_state` (new domain)

| table | kind | status | rows | PK | PIT | idx | what |
|---|---|---|---:|---|---|---:|---|
| `build_run` | table | pilot-built | - | run_id | - | 0 |  |
| `company_membership_pit` | table | pilot-built | 10,895 | isin,index_code,added_on | added_on,removed_on | 2 |  |
| `company_ownership_pit` | table | pilot-built | 49,126 | isin,quarter_end | quarter_end,known_at | 1 |  |
| `company_sector_pit` | table | pilot-built | 0 | isin,valid_from | valid_from,valid_to | 2 |  |
| `company_state_daily` | table | pilot-built | 7,258,000 | isin,date | date,known_at | 3 |  |
| `company_theme_pit` | table | designed-only | - | isin,theme,valid_from | valid_from,valid_to | 1 |  |
| `corporate_action_class` | table | designed-only | - | isin,ex_date,action_type | known_at | 1 |  |
| `event_calendar` | table | designed-only | - | event_id | event_date,known_at | 1 |  |
| `event_day0` | table | pilot-built | 3,010,610 | event_id,isin | known_at,session_0 | 2 |  |
| `event_leakage_window` | table | pilot-built | 0 | event_id,isin,offset | date,known_at | 1 |  |
| `fno_oi_daily` | table | designed-only | - | date,underlying,expiry,strike,option_type | date | 1 |  |
| `index_list` | table | pilot-built | 133 | index_code | - | 0 |  |
| `ipo_grey_market` | table | designed-only | - | isin,date,phase | date | 0 |  |
| `isin_rekey_map` | table | pilot-built | 0 | old_isin,new_isin | - | 1 |  |
| `macro_claim` | table | pilot-built | 21,552 | claim_id | known_at | 3 |  |
| `macro_claim_target` | table | pilot-built | 44,742 | claim_id,target_kind,target_id | - | 1 |  |
| `macro_doc` | table | pilot-built | 456 | doc_id | event_date,known_at | 0 |  |
| `sector_flow_daily` | table | designed-only | - | date,sector | date | 0 |  |
| `series_meta` | table | designed-only | - | series_code | - | 0 |  |
| `series_observation` | table | designed-only | - | series_code,period_start | period_start,known_at | 1 |  |
| `theme_map` | table | pilot-built | 0 | theme,match_kind,match_value | - | 0 |  |
| `commodity_price_daily` | view | view | - | - | - | 0 |  |
| `freight_rate_daily` | view | view | - | - | - | 0 |  |
| `mcap_bucket_interval` | view | view | - | - | - | 0 |  |
| `policy_target` | view | view | - | - | - | 0 |  |
| `price_band_daily` | view | view | - | - | - | 0 |  |
| `rainfall_daily` | view | view | - | - | - | 0 |  |
| `rate_series_daily` | view | view | - | - | - | 0 |  |
| `rural_wage_series` | view | view | - | - | - | 0 |  |
| `shipment_transit` | view | view | - | - | - | 0 |  |

### 2.9 `metric_state` (new domain)

| table | kind | status | rows | PK | PIT | idx | what |
|---|---|---|---:|---|---|---:|---|
| `audit_opinion_detail` | table | designed-only | - | isin,period_end,filing_kind | known_at | 0 |  |
| `bank_deposit_rate` | table | designed-only | - | isin,period_end,bucket | known_at | 0 |  |
| `bank_loan_book_repricing` | table | designed-only | - | isin,period_end,benchmark | known_at | 0 |  |
| `build_run` | table | pilot-built | - | run_id | - | 0 |  |
| `capex_project` | table | designed-only | - | isin,project,announced_on | known_at | 1 |  |
| `company_capacity_utilisation` | table | designed-only | - | isin,period_end,product | known_at | 0 |  |
| `company_cost_geography` | table | designed-only | - | isin,period_end,location | known_at | 0 |  |
| `company_cost_structure` | table | designed-only | - | isin,period_end,basis,input_key | known_at | 1 |  |
| `company_debt_mix` | table | designed-only | - | isin,period_end,bucket | known_at | 0 |  |
| `company_fx_exposure` | table | designed-only | - | isin,period_end | known_at | 0 |  |
| `company_import_content` | table | designed-only | - | isin,period_end | known_at | 0 |  |
| `company_interest_cover` | table | pilot-built | 12,762 | isin,period_end,basis | known_at | 1 |  |
| `company_kmp` | table | designed-only | - | isin,person,role,from_date | known_at | 0 |  |
| `company_metric_series` | table | pilot-built | 1,056,589 | isin,metric_key,period_end,period_kind,basis | known_at | 2 |  |
| `company_operating_metrics` | table | designed-only | - | isin,period_end,metric | known_at | 0 |  |
| `company_price_revision` | table | designed-only | - | isin,announced_on,product,source_doc_id | known_at | 1 |  |
| `company_result_pit` | table | pilot-built | 60,023 | isin,period_end,basis | known_at | 1 |  |
| `company_revenue_geography` | table | designed-only | - | isin,period_end,country | known_at | 0 |  |
| `company_segment_pnl` | table | pilot-built | 34,451 | isin,segment,period_end,metric,basis | known_at | 2 |  |
| `company_working_capital` | table | pilot-built | 9,144 | isin,period_end,basis | known_at | 0 |  |
| `competitor_action` | table | designed-only | - | isin,effective_on,action | known_at | 0 |  |
| `entity_relations` | table | designed-only | - | src_name,dst_name,relation | valid_from,valid_to,known_at | 0 |  |
| `fund_raise` | table | designed-only | - | isin,raise_id | known_at | 0 |  |
| `fund_utilisation` | table | designed-only | - | isin,raise_id,object,as_of | as_of,known_at | 0 |  |
| `guidance_vs_actual` | table | designed-only | - | isin,metric,guided_on,period_end | known_at | 1 |  |
| `import_duty_structure` | table | designed-only | - | hs_code,notification | known_at | 0 |  |
| `industry_capacity_pipeline` | table | designed-only | - | basic_industry,isin,announced_on | known_at | 0 |  |
| `market_share_shift` | table | designed-only | - | isin,period_end,product | known_at | 0 |  |
| `order_book_contract` | table | designed-only | - | isin,contract_id | known_at | 0 |  |
| `order_intake` | table | designed-only | - | isin,period_end | known_at | 0 |  |
| `pass_through_history` | table | designed-only | - | isin,input_series,shock_start | - | 0 |  |
| `promoter_pledge_event` | table | designed-only | - | isin,event_date,pledgor,action | event_date,known_at | 0 |  |
| `rating_action` | table | designed-only | - | isin,action_date,agency,instrument | known_at | 0 |  |
| `subsidy_register` | table | designed-only | - | isin,scheme,period_end | known_at | 0 |  |
| `supply_link` | table | designed-only | - | src_isin,dst_isin,relation | known_at | 0 |  |
| `tariff_exposure` | table | designed-only | - | isin,hs_code,country,effective_on | known_at | 0 |  |
| `xbrl_concept_map` | table | pilot-built | 110 | taxonomy,concept | - | 1 |  |

### 2.10 `chunks_v3` (new domain)

| table | kind | status | rows | PK | PIT | idx | what |
|---|---|---|---:|---|---|---:|---|
| `build_run` | table | pilot-built | - | run_id | - | 0 |  |
| `chunk` | table | pilot-built | 36,494 | chunk_id | known_at,event_date | 4 |  |
| `chunk_entity` | table | pilot-built | 107,121 | isin,symbol,chunk_id | - | 1 |  |
| `chunk_fts` | virtual | pilot-built | - | - | - | 0 |  |
| `chunk_tag` | table | pilot-built | 104,765 | tag,chunk_id | - | 1 |  |
| `chunk_vec_ref` | table | pilot-built | 0 | model,chunk_id | - | 1 |  |
| `coverage_scorecard` | table | pilot-built | 0 | measured_on,doc_type,tag | - | 0 |  |
| `doc` | table | pilot-built | 433 | doc_id | event_date,known_at | 3 |  |
| `result_note` | table | pilot-built | 0 | note_id | known_at | 1 |  |
| `tag_vocab` | table | pilot-built | 32 | tag | - | 0 |  |

The interim `results_notes.db` (17,989 rows, 80 MB, live) is retired in place: superseded by
`chunks_v3.result_note` + `doc`, kept read-only for replay until the v3 store is complete. It is not
part of the final runnable SQL.

**DDL deltas against SCHEMA_V3 (all four are in the final SQL):**

1. `chunks_v3.doc` gains `needs_ocr INTEGER NOT NULL DEFAULT 0` (added by the actual pilot build).
2. `chunks_v3.chunk_entity(isin, symbol, chunk_id)` existed in the built store but not in SCHEMA_V3:
   the entity bridge that survives a symbol change.
3. `market_state.macro_claim` gains the six pilot columns the RIPPLE trigger reads: `paraphrase`,
   `known_at`, `stratum`, `conditions`, `quote_ok`, `effective_pit_conf`, plus `ix_mclaim_known`.
4. External series: `series_meta` + `series_observation` (one table) with six compatibility views
   (`commodity_price_daily`, `freight_rate_daily`, `rainfall_daily`, `rural_wage_series`,
   `shipment_transit`, `rate_series_daily`) so CASE_MAP names still resolve and a new series is a row,
   not a table. `series_observation` adds the `known_at`/`pit_conf` that `mkt_commodity_daily` lacks.

**Live-store drift found (recorded, not fixed here):** `mkt_bse_eq_daily.isin` is 36% filled (join on
`sc_code`); `corporate_documents` publication/dissem fill is 37%/59%; `mkt_commodity_daily` has no
`known_at`; `annual_financials.interest_coverage` cannot rank solvency (0 rows < 2.5x in 3,245 FY26
rows, hence `company_interest_cover`); `bse_announcements.ann` has no `(symbol, DissemDT)` index
(2.4 s query); `results_xbrl.segment` and `.npa` never existed (mapped to `facts.concept`).

---

## 3. Bank coverage matrix

Membership counts: a case can belong to several families, so family n sums to more than 1,073. Overall: **a 629 / b 435 / c 9**.

| family | n | a | b | c |
|---|---:|---:|---:|---:|
| 1 lookup | 136 | 85 | 51 | 0 |
| 2 number | 185 | 121 | 64 | 0 |
| 3 change-over-time | 122 | 76 | 46 | 0 |
| 4 screen | 52 | 38 | 14 | 0 |
| 5 cross-document | 11 | 9 | 2 | 0 |
| 6 policy->companies | 95 | 69 | 20 | 6 |
| 7 company->policy | 33 | 25 | 2 | 6 |
| 8 peers | 50 | 31 | 18 | 1 |
| 9 event-window | 117 | 92 | 25 | 0 |
| 10 opinions | 19 | 18 | 1 | 0 |
| 11 point-in-time | 72 | 37 | 34 | 1 |
| 12 when/timeline | 99 | 47 | 52 | 0 |
| 13 inverse-screen | 17 | 13 | 4 | 0 |
| 14 governance/audit | 60 | 33 | 27 | 0 |
| 15 move->why | 39 | 30 | 8 | 1 |
| 16 input-cost | 137 | 34 | 103 | 0 |
| 17 business-economics | 40 | 28 | 12 | 0 |
| 18 forward-policy | 58 | 26 | 32 | 0 |
| 19 second-order | 70 | 21 | 49 | 0 |
| 20 out-of-scope | 20 | 10 | 10 | 0 |

### By bank
| bank | n | a | b | c |
|---|---:|---:|---:|---:|
| shivam30 | 30 | 19 | 11 | 0 |
| variations300 | 300 | 192 | 102 | 6 |
| open300 | 300 | 158 | 141 | 1 |
| ripple200 | 200 | 44 | 155 | 1 |
| reddit200 | 243 | 216 | 26 | 1 |

### By entity level
| level | n | a | b | c |
|---|---:|---:|---:|---:|
| stock | 584 | 421 | 161 | 2 |
| theme | 28 | 17 | 7 | 4 |
| industry | 181 | 59 | 121 | 1 |
| policy | 93 | 48 | 45 | 0 |
| index | 35 | 8 | 26 | 1 |
| market-wide | 95 | 50 | 45 | 0 |
| market-cap bucket | 15 | 9 | 6 | 0 |
| price band | 4 | 3 | 1 | 0 |
| sector | 15 | 7 | 8 | 0 |
| macro | 23 | 7 | 15 | 1 |

### Class a: what promoted 162 cases on 2026-10-29

`needs_new_table` cases whose blocker table was built by the T1/pilot runs, **and** the table holds at
least one row for that case's ISIN (the acceptance rule; this is why `chunks_v3` 64 -> 35 and
`company_segment_pnl` 12 -> 1):

| built table | cases promoted |
|---|---:|
| `macro_claim_target` | 47 |
| `xbrl_concept_map` | 35 |
| `chunks_v3` (doc/chunk) | 35 |
| `event_day0` | 24 |
| `company_metric_series` | 14 |
| `company_state_daily` | 6 |
| `company_segment_pnl` | 1 |

Chunks_v3 is pilot-scale (433 docs, 90 ISINs, 36,494 chunks): the promoted `chunks_v3` cases are
answerable for the companies whose docs are in the pilot; the rest stay `b` on `chunks_v3.doc`
originals/full chunk pass. `company_segment_pnl` holds 1,547 ISINs, 32 of the 60 pilot companies.
`company_metric_series` holds 3,267 ISINs, 57 of 60.

The full per-case list (case_id, class, tables, target, reason) is
`tasks/SCHEMA_FINAL_CASES_2026-10-29.jsonl`.

---

## 4. NOT IN DATA (9 cases)

| cases | n | reason |
|---|---:|---|
| MB0191, MB0193, MB0194, MB0195, MB0197, MB0198 | 6 | No published Indian refurbished/second-hand electronics sales series from any exchange, industry body or free source. |
| MB0445 | 1 | Analyst consensus and target prices are a paid-only source. Shivam's ruling (2026-10-19): no consensus store; expectations come from the company's own guidance plus its historical trend. |
| MB0810 | 1 | Asks for a price on a future date (Diwali 2027). A future price is not data we can hold; the answer is a labelled scenario range, not a stored fact. |
| MB0936 | 1 | Novelis is an unlisted Hindalco subsidiary; only consolidated segment P&L is filed. No cost-curve data exists anywhere we can hold. |

Also answered **as** the NID statement (class `a`, `reason` starts "NOT IN DATA is the expected
answer"): MB0196, MB0200 (refurbished sales), MB0616, MB0627 (consensus), MB0629 (investor
holdings). Their rubrics ask for the absence, so the NID wording is the correct answer.

No case was pushed to `c` to make the numbers look better; the 9 are the same rows
`arch_v3/COVERAGE.md` marked `never`. Two designs were considered and rejected for `c`:
crawling broker target prices (paid, no consistent cross-section) and forecasting Diwali-2027 price
(a forecast is not data).

---

## 5. Build order for the remaining (b) work

Ordered by cases unblocked, with prerequisites. `fetch` rows are network jobs; `table` rows are readers/population over held data. Hours are engineering estimates at 8 workers.

| # | target | cases | kind | source | method | hours | depends on |
|---:|---|---:|---|---|---|---:|---|
| 1 | `chunks_v3.doc` | 75 | fetch | BSE/NSE originals + held raw store | fetch the missing originals, then chunker_v3; gated by golden-rule step 5 | 8.0 | step-5 pilot gate; alias map |
| 2 | `market_state.commodity_price_daily` | 62 | fetch | LME/MCX/NSE currency, crude, coal, metals | 40 series x 2,000 days -> series_observation; 13 held series gain known_at | 8.0 | - |
| 3 | `metric_state.company_cost_structure` | 31 | table | AR raw-material note + XBRL COGS | deterministic share vs COGS + 3 h reader | 3.0 | xbrl_concept_map |
| 4 | `equity_intelligence.mkt_nse_full_daily` | 19 | fetch | NSE/BSE archive | bhavcopy backfill for delisted/SME/BSE-only, sc_code joins | 4.0 | - |
| 5 | `metric_state.company_capacity_utilisation` | 19 | table | AR capacity note, deck 'Capacity', concall | 6 h reader, dated statements | 6.0 | - |
| 6 | `market_state.fno_oi_daily` | 19 | fetch | NSE F&O bhavcopy | fetch 1,936 sessions, load per contract | 4.5 | - |
| 7 | `metric_state.company_operating_metrics` | 17 | table | concall 645k items + deck 13.6M facts | 4 h reader | 4.0 | - |
| 8 | `market_state.company_membership_pit` | 15 | fetch | 446 NSE index circulars + snapshot | crawl/parse notices, 3 min load | 2.0 | - |
| 9 | `metric_state.industry_capacity_pipeline` | 13 | table | capex_project + PIB approvals | 2 h after capex_project | 2.0 | capex_project |
| 10 | `metric_state.company_debt_mix` | 13 | table | AR borrowings-maturity note | 25 min deterministic + 3 h reader | 3.5 | - |
| 11 | `metric_state.capex_project` | 12 | table | concall/deck capex statements | 4 h reader | 4.0 | - |
| 12 | `metric_state.company_segment_pnl` | 11 | table | ar_facts segment 145,742 + deck + XBRL | 45 min parse + 2 h validation; 34,451 rows / 1,547 ISINs already built | 1.0 | chunks_v3 tags (optional) |
| 13 | `metric_state.audit_opinion_detail` | 10 | table | filings.audit_opinion + AR auditor text | 2 h reader | 2.0 | - |
| 14 | `metric_state.supply_link` | 9 | table | AR related-party 575k facts + concall | curated edges, 3 h | 3.0 | - |
| 15 | `metric_state.tariff_exposure` | 9 | fetch | customs schedules (fetch) + revenue geography | 5 h after the schedule | 5.0 | company_revenue_geography + customs fetch |
| 16 | `metric_state.company_revenue_geography` | 7 | table | segment note | 40 min | 0.7 | - |
| 17 | `market_state.freight_rate_daily` | 7 | fetch | WCI/Baltic/container | fetch + 5 min load | 4.0 | - |
| 18 | `metric_state.company_fx_exposure` | 7 | table | AR FX/hedging note + concall | 3 h reader | 3.0 | - |
| 19 | `market_state.event_calendar` | 6 | table | policy_events + macro_events + curated | 2 h curation | 2.0 | - |
| 20 | `metric_state.market_share_shift` | 6 | table | company volumes + industry-body fetch | 3 h after the volume series | 3.0 | industry volume fetch |
| 21 | `metric_state.fund_raise` | 5 | table | board/EGM/placement announcements | 3 h reader | 3.0 | - |
| 22 | `metric_state.order_book_contract` | 4 | table | order-win announcements | 3 h | 3.0 | - |
| 23 | `metric_state.rating_action` | 4 | table | BSE rating headlines + attachments | 1 h | 1.0 | - |
| 24 | `metric_state.promoter_pledge_event` | 4 | table | announcements + SHP cells | 2 h | 2.0 | - |
| 25 | `market_state.rural_wage_series` | 4 | fetch | MGNREGA MIS / Labour Bureau | fetch + 5 min | 4.0 | - |
| 26 | `metric_state.bank_deposit_rate` | 4 | table | AR deposit schedule | 2 h | 2.0 | - |
| 27 | `market_state.company_sector_pit` | 3 | table | BSE scrip-master history + NSE classification | curate 6,940 x ~2 intervals; 5 min load | 3.0 | - |
| 28 | `metric_state.order_intake` | 3 | table | concall order-book + deck | 3 h | 3.0 | - |
| 29 | `metric_state.guidance_vs_actual` | 3 | table | concall guidance + metric series | 30 min after series | 0.5 | company_metric_series |
| 30 | `metric_state.company_kmp` | 3 | table | AR remuneration/governance facts | 2 h | 2.0 | - |
| 31 | `metric_state.entity_relations` | 3 | table | AR auditor/subsidiary facts | 2 h | 2.0 | - |
| 32 | `market_state.event_leakage_window` | 3 | table | event_day0 + px_daily + deals | 25 min (300k material events x 21 offsets) | 0.5 | - |
| 33 | `market_state.rainfall_daily` | 3 | fetch | IMD district rainfall | fetch + 5 min | 4.0 | - |
| 34 | `chunks_v3.result_note` | 2 | fetch | BSE results-note PDFs | fetch + reader, 25 min | 0.5 | - |
| 35 | `market_state.company_theme_pit` | 2 | table | curated theme map | 20 min | 0.4 | - |
| 36 | `market_state.corporate_action_class` | 2 | table | corporate_actions + announcement text | 10 min + 20 min spot check | 0.5 | - |
| 37 | `metric_state.import_duty_structure` | 2 | fetch | CBIC notifications fetch | 2 h | 2.0 | - |
| 38 | `metric_state.bank_loan_book_repricing` | 2 | table | AR/deck repricing disclosures | 3 h | 3.0 | - |
| 39 | `metric_state.company_cost_geography` | 2 | table | location note | 40 min | 0.7 | - |
| 40 | `metric_state.competitor_action` | 2 | table | concall competitor statements | 2 h | 2.0 | - |
| 41 | `market_state.isin_rekey_map` | 1 | table | px_bse + security_master + corporate_actions + rekey log | curate ~2,000 rows, verify | 16.0 | - |
| 42 | `metric_state.subsidy_register` | 1 | table | PIB/PLI + AR other income | 2 h | 2.0 | - |
| 43 | `market_state.price_band_daily` | 1 | table | see SCHEMA_V3 DDL comment | build per DDL | 2.0 | - |
| 44 | `market_state.sector_flow_daily` | 1 | table | deal tape + sector map | 15 min | 0.3 | - |
| 45 | `metric_state.company_price_revision` | 1 | table | concall pricing items + deck | 3 h | 3.0 | - |
| 46 | `market_state.shipment_transit` | 1 | fetch | carrier/port schedules | fetch + 5 min | 4.0 | - |
| 47 | `market_state.ipo_grey_market` | 1 | fetch | unofficial GMP | 30 min | 0.5 | - |
| 48 | `market_state.rate_series_daily` | 1 | fetch | RBI/NSE 10Y G-sec | fetch + 5 min | 4.0 | - |

Total engineering estimate for all (b) work: **144 h** (54 h fetch jobs, 89 h table builds/readers; wall-clock is dominated by the reader and fetch queues, not the coding).


**Sequenced build (the order to actually run):**

1. **Wiring, 0 h fetch** (0.5 day): point the FACTS/EVIDENCE/RIPPLE planners at the 7 built tables
   (`company_metric_series`, `company_segment_pnl`, `macro_claim_target`, `event_day0`,
   `company_state_daily`, `xbrl_concept_map`, `chunks_v3`). This alone makes the 162 promoted cases
   reachable; no new data.
2. **Population of built tables** (~1 day): `company_segment_pnl` beyond 1,547 ISINs; `chunks_v3`
   beyond the 433-doc pilot cap needs the step-6 chunk pass, which is gated by the pilot result.
3. **Deterministic builds over held data** (~1.5 days): `event_leakage_window`, `sector_flow_daily`,
   `company_revenue_geography`, `company_working_capital`/`interest_cover` already done,
   `corporate_action_class`, `company_theme_pit`, `guidance_vs_actual`, `pass_through_history`.
4. **Reader builds over held documents** (~5 days at 8 workers, free models only):
   `company_cost_structure` (3 h), `company_capacity_utilisation` (6 h), `company_operating_metrics`
   (4 h), `company_debt_mix` (3.5 h), `capex_project` (4 h), `order_intake` (3 h), `rating_action`
   (1 h), `audit_opinion_detail` (2 h), plus the long tail. Each is gated on a hand-check precision
   like `macro_claim_target` (0.994 precision / 0.93 recall measured).
5. **Fetch stream** (~2-3 days of machine time): commodities 62 cases, originals 75, bhavcopy 19,
   F&O 19, index circulars 15. This is what moves 79.5% -> 99.2%, and it needs Shivam's approval
   (net-heavy jobs are refused in market hours).
6. **Then, and only then, the full run**: chunking -> re-embedding (golden rule steps 5-6).

---

## 6. Open decisions for Shivam

1. **Embedding dimension / model spend (the one genuinely his call).** The schema supports any
   `(model, row_idx, dim)` in `chunk_vec_ref`. The pending choice is Nemotron-3-Embed-8B 4096-d
   (~$20 on DeepInfra for the FY26 chunks) vs an NVFP4/Qwen variant (~$5.6) with a Nemotron-3.5
   reranker. 4096-d is 56 GB for 3.4M chunks and must be memory-mapped; a smaller dimension changes
   the NumPy folder layout, not the SQL.
2. **Fetch-stream approval.** 211 of the 435 (b) cases are fetch-class; without them the ceiling is
   79.5% and the 95% pilot gate cannot pass. The three biggest: commodity/freight/rain/wage series
   (62), exchange originals (75), bhavcopy backfill (19). Approve the queue (net-heavy windows are
   already enforced).
3. **F&O history coverage.** The 19 OI/PCR/rollover cases assume NSE's F&O archive is free and
   complete back to 2019. If the archive is partial, those cases should be re-labelled `c`.
4. **Retire `results_notes.db` after v3 parity.** It is superseded by `chunks_v3.result_note`; keep
   it read-only for replay until the v3 store is complete. Needs a yes/no.
5. **`company_sector_pit` PIT confidence.** The T1 build labels companies from today's
   classification (`pit_conf` 0.6 backcast). Accept that for history, or fetch BSE scrip-master
   history (15 cases, 3 h) to raise it.
6. **Planner entity/relevance gate.** Class `a` is schema-level only: pilot60 hand-check precision
   was 5%. Before the bank is called "answered", the planner needs an entity gate (the right ISIN,
   the right period) — a code task, not schema. This is the real blocker to the 95% gate, alongside
   the fetch stream.
7. **One domain file or two?** `market_state` + `metric_state` + `chunks_v3` are three files and one
   writer each. Merging `market_state`/`metric_state` would save a file but couple two build jobs;
   the current split is one-writer-safe. No action unless he prefers fewer files.

## 7. Validation

- `python -c "import sqlite3;c=sqlite3.connect(':memory:');c.executescript(open('tasks/SCHEMA_FINAL_2026-10-29.sql',encoding='utf-8').read());print('ok')"` -> `ok`
  (10 attached domains, 151 objects: 139 tables - 47 live-store, 24 snapshot, 68 new-domain
  incl. 1 virtual FTS5 - plus 9 views and 3 triggers, and the live indexes copied from `sqlite_master`).
- Every table named in `CASE_MAP.jsonl` or `reality_engine/query/planners/*.py` exists in the final
  SQL or is explicitly retired (check prints `MISSING TABLES: none`). Retired: `arch_v3.result_note`
  (now `chunks_v3.result_note`), `results_notes.db`, `opinions.db`, `chunks_v2`.
- `SCHEMA_FINAL_CASES_2026-10-29.jsonl`: 1,073 rows, every row has `case_id`, `class` in {a,b,c},
  non-empty `tables`, and every `c` row has a `reason`.
- `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` -> 55 tests OK, no code change.
- Drift against the generated context pack (repo/probes win): master bank is 1,073 rows not 1,030
  (`CASE_MAP.jsonl` predates the last 43 reddit200 rows - MB1031-MB1073, all classified here);
  `document_chunks` is 2,939,096 rows, not the pack's 2.3M (`sqlite_stat1` stale); `shareholding` is a
  40-row view while the live PIT store is `shp_index` (50,838 rows); `insider_trades_v2` holds
  333,712 rows, so NG06 "empty insider store" is stale.
- Spot checks (read-only, immutable): AEROFLEX `INE024001021` has 439 `company_metric_series`,
  26 `company_result_pit`, 773 `company_state_daily`, 388 `event_day0` rows; the pilot `doc` store
  covers 90 ISINs. `macro_claim_target` 44,742 rows with 0.994 precision / 0.94 recall from the
  independent 80-claim check.
