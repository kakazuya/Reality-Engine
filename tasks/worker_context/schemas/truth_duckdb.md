# truth_duckdb schema

File: `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\snapshots\truth_2026-10-19.duckdb` (8.5 GB)

## adj_factor
rows: 2.5k · key columns: entity_id, ex_date, kind, price_factor

- `entity_id` VARCHAR
- `ex_date` TIMESTAMP
- `kind` VARCHAR
- `price_factor` DOUBLE

## adj_factor_cum
rows: 2.5k · key columns: entity_id, ex_date, run_l, tot_l

- `entity_id` VARCHAR
- `ex_date` DATE
- `run_l` DOUBLE
- `tot_l` DOUBLE

## ar_docs
rows: 33.7k · key columns: isin, symbol, fiscal_year, known_at_utc, filed_at, doc_id

- `doc_id` BIGINT
- `isin` VARCHAR
- `symbol` VARCHAR
- `company` VARCHAR
- `fiscal_year` VARCHAR
- `fiscal_year_source` VARCHAR
- `filed_at` VARCHAR
- `filed_at_source` VARCHAR
- `sha256` VARCHAR
- `n_pages` BIGINT
- `n_text_pages` BIGINT
- `n_pieces` BIGINT
- `status` VARCHAR
- `error` VARCHAR
- `ts` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## ar_facts
rows: 32.4M · key columns: isin, symbol, period, fiscal_year, known_at_utc, filed_at, doc_id, item

- `fact_id` BIGINT
- `doc_id` BIGINT
- `piece` BIGINT
- `isin` VARCHAR
- `symbol` VARCHAR
- `fiscal_year` VARCHAR
- `filed_at` VARCHAR
- `page` BIGINT
- `category` VARCHAR
- `item` VARCHAR
- `value_raw` VARCHAR
- `value` DOUBLE
- `unit` VARCHAR
- `period` VARCHAR
- `basis` VARCHAR
- `quote` VARCHAR
- `model` VARCHAR
- `value_check` VARCHAR
- `prompt_version` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## board_meetings
rows: 120.6k · key columns: isin, symbol, known_at_utc

- `symbol` VARCHAR
- `isin` VARCHAR
- `idx` VARCHAR
- `meeting_date` VARCHAR
- `purpose` VARCHAR
- `description` VARCHAR
- `intimated_at` VARCHAR
- `industry` VARCHAR
- `attachment` VARCHAR
- `fetched_at` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## bse_ann
rows: 1.9M · key columns: symbol, known_at_utc, NEWSID

- `NEWSID` VARCHAR
- `SCRIP_CD` VARCHAR
- `ATTACHMENTNAME` VARCHAR
- `NEWSSUB` VARCHAR
- `HEADLINE` VARCHAR
- `CATEGORYNAME` VARCHAR
- `SUBCATNAME` VARCHAR
- `NEWS_DT` VARCHAR
- `DT_TM` VARCHAR
- `News_submission_dt` VARCHAR
- `DissemDT` VARCHAR
- `QUARTER_ID` VARCHAR
- `Fld_Attachsize` VARCHAR
- `ANNOUNCEMENT_TYPE` VARCHAR
- `symbol` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## bse_code_isin
rows: 13.1k · key columns: isin, sc_code

- `sc_code` VARCHAR
- `isin` VARCHAR
- `first_date` DATE
- `last_date` DATE
- `src` VARCHAR

## bse_deals
rows: 135.5k · key columns: date, known_at_utc, sc_code

- `date` VARCHAR
- `deal_type` VARCHAR
- `sc_code` VARCHAR
- `scrip_name` VARCHAR
- `client_name` VARCHAR
- `buy_sell` VARCHAR
- `quantity` DOUBLE
- `price` DOUBLE
- `seq` BIGINT
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## bse_insider
rows: 153.9k · key columns: isin, known_at_utc, file

- `file` VARCHAR
- `line_no` BIGINT
- `company` VARCHAR
- `isin` VARCHAR
- `person` VARCHAR
- `raw_json` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## bse_master
rows: 65.1k · key columns: isin, bse_symbol, sc_code

- `sc_code` VARCHAR
- `isin` VARCHAR
- `bse_symbol` VARCHAR
- `name` VARCHAR
- `status` VARCHAR
- `bse_group` VARCHAR
- `face_value` DOUBLE

## cc_docs
rows: 1.2k · key columns: isin, symbol, known_at_utc, filed_at, doc_id

- `doc_id` BIGINT
- `isin` VARCHAR
- `symbol` VARCHAR
- `filed_at` VARCHAR
- `status` VARCHAR
- `model` VARCHAR
- `key_name` VARCHAR
- `chars` BIGINT
- `in_tok` BIGINT
- `out_tok` BIGINT
- `cost_usd` DOUBLE
- `seconds` DOUBLE
- `error` VARCHAR
- `run_at` VARCHAR
- `priority` BIGINT
- `period_discussed` VARCHAR
- `period_q` BIGINT
- `period_fy` BIGINT
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## cc_item_checks
rows: 87.9k · key columns: doc_id

- `doc_id` BIGINT
- `list_name` VARCHAR
- `idx` BIGINT
- `value_in_quote` BIGINT
- `period_in_quote` BIGINT
- `direction_supported` BIGINT
- `speaker_role` VARCHAR
- `speaker` VARCHAR
- `metric_key` VARCHAR
- `value_low` DOUBLE
- `value_high` DOUBLE
- `value_is_pct` BIGINT
- `item_fy` BIGINT
- `computed_direction` VARCHAR
- `prev_doc_id` BIGINT
- `prev_value_mid` DOUBLE
- `checked_at` VARCHAR

## cc_items
rows: 87.9k · key columns: isin, period, known_at_utc, filed_at, doc_id, metric

- `doc_id` BIGINT
- `list_name` VARCHAR
- `idx` BIGINT
- `isin` VARCHAR
- `filed_at` VARCHAR
- `metric` VARCHAR
- `value` VARCHAR
- `unit` VARCHAR
- `period` VARCHAR
- `basis` VARCHAR
- `direction` VARCHAR
- `firmness` VARCHAR
- `signal` VARCHAR
- `statement` VARCHAR
- `quote` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## circuit_hits
rows: 482.3k · key columns: symbol, date, known_at_utc

- `date` VARCHAR
- `symbol` VARCHAR
- `series` VARCHAR
- `high_low` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## company_industry
rows: 3.2k · key columns: isin, symbol

- `isin` VARCHAR
- `symbol` VARCHAR
- `series` VARCHAR
- `macro` VARCHAR
- `sector` VARCHAR
- `industry` VARCHAR
- `basic_industry` VARCHAR
- `index_list` VARCHAR
- `listing_date` VARCHAR
- `fetched_at` VARCHAR

## corp_action
rows: 16.8k · key columns: entity_id, ex_date, kind, params, text, source, factor, prev_close

- `entity_id` VARCHAR
- `ex_date` TIMESTAMP
- `kind` VARCHAR
- `params` VARCHAR
- `text` VARCHAR
- `source` VARCHAR
- `factor` DOUBLE
- `prev_close` DOUBLE
- `ex_close` DOUBLE
- `ex_open` DOUBLE
- `price_factor` DOUBLE
- `observed_ratio` DOUBLE
- `factor_status` VARCHAR
- `tr_factor` DOUBLE
- `combined_factor` DOUBLE
- `residual` DOUBLE

## corp_action_raw
rows: 36.5k · key columns: isin

- `entity_id` VARCHAR
- `isin` VARCHAR
- `ex_date` DATE
- `kind` VARCHAR
- `params` VARCHAR
- `text` VARCHAR
- `source` VARCHAR

## corporate_actions
rows: 18.2k · key columns: isin, symbol, known_at_utc, id

- `id` BIGINT
- `isin` VARCHAR
- `symbol` VARCHAR
- `company_name` VARCHAR
- `subject` VARCHAR
- `action_type` VARCHAR
- `ex_date` DATE
- `rec_date` DATE
- `bc_start_date` DATE
- `bc_end_date` DATE
- `nd_start_date` DATE
- `nd_end_date` DATE
- `broadcast_date` DATE
- `face_value` DOUBLE
- `series` VARCHAR
- `industry` VARCHAR
- `source` VARCHAR
- `fetched_at` TIMESTAMP
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## deck_chart_trends
rows: 531 · key columns: isin, symbol, known_at_utc, known_at

- `sha256` VARCHAR
- `page_no` BIGINT
- `symbol` VARCHAR
- `isin` VARCHAR
- `known_at` VARCHAR
- `measure` VARCHAR
- `span` VARCHAR
- `trend` VARCHAR
- `model` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## deck_facts
rows: 13.6M · key columns: isin, symbol, period, known_at_utc, metric

- `isin` VARCHAR
- `symbol` VARCHAR
- `doc_type` VARCHAR
- `sha256` VARCHAR
- `page_no` BIGINT
- `prompt_version` VARCHAR
- `model` VARCHAR
- `line_no` BIGINT
- `metric` VARCHAR
- `period` VARCHAR
- `raw_number` VARCHAR
- `value` DOUBLE
- `unit` VARCHAR
- `is_final` BIGINT
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## deck_pages
rows: 815.8k · key columns: isin, symbol, known_at_utc, doc_id

- `sha256` VARCHAR
- `page_no` INTEGER
- `prompt_version` VARCHAR
- `doc_id` VARCHAR
- `isin` VARCHAR
- `symbol` VARCHAR
- `doc_type` VARCHAR
- `route` VARCHAR
- `n_facts` INTEGER
- `status` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## deck_sources
rows: 26.4k · key columns: isin, symbol, known_at_utc, known_at

- `source` VARCHAR
- `source_id` VARCHAR
- `symbol` VARCHAR
- `isin` VARCHAR
- `exch_code` VARCHAR
- `known_at` VARCHAR
- `title` VARCHAR
- `url` VARCHAR
- `sha256` VARCHAR
- `size_bytes` BIGINT
- `status` VARCHAR
- `error` VARCHAR
- `fetched_at` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## div_factor
rows: 11.1k · key columns: entity_id, ex_date, tr_factor

- `entity_id` VARCHAR
- `ex_date` TIMESTAMP
- `tr_factor` DOUBLE

## div_factor_cum
rows: 11.1k · key columns: entity_id, ex_date, run_l, tot_l

- `entity_id` VARCHAR
- `ex_date` DATE
- `run_l` DOUBLE
- `tot_l` DOUBLE

## entity
rows: 6.2k · key columns: entity_id, first_date, last_date, n_days, latest_isin, latest_symbol, on_nse, bse_only_days

- `entity_id` VARCHAR
- `first_date` DATE
- `last_date` DATE
- `n_days` BIGINT
- `latest_isin` VARCHAR
- `latest_symbol` VARCHAR
- `on_nse` BOOLEAN
- `bse_only_days` BOOLEAN

## etf_px
rows: 314.2k · key columns: isin, symbol, date

- `date` VARCHAR
- `symbol` VARCHAR
- `isin` VARCHAR
- `close` DOUBLE
- `volume` DOUBLE
- `value_inr` DOUBLE
- `source` VARCHAR

## events
rows: 3.3M · key columns: isin, known_at_utc

- `isin` VARCHAR
- `known_at_utc` TIMESTAMP
- `kind` VARCHAR
- `source_ref` VARCHAR
- `summary` VARCHAR

## fii_dii_cash
rows: 1.9k · key columns: date, known_at_utc

- `date` VARCHAR
- `fii_purchase_cr` DOUBLE
- `fii_sales_cr` DOUBLE
- `fii_net_cr` DOUBLE
- `dii_purchase_cr` DOUBLE
- `dii_sales_cr` DOUBLE
- `dii_net_cr` DOUBLE
- `nifty_close` DOUBLE
- `nifty_prev_close` DOUBLE
- `nifty_change_pct` DOUBLE
- `source` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## fund_nav
rows: 322.1k · key columns: isin, date, known_at_utc

- `isin` VARCHAR
- `date` VARCHAR
- `nav` DOUBLE
- `scheme_code` VARCHAR
- `scheme_name` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## index_tri
rows: 13.5k · key columns: date

- `index_name` VARCHAR
- `date` VARCHAR
- `tri` DOUBLE
- `price` DOUBLE
- `source` VARCHAR
- `method` VARCHAR
- `fetched_at` VARCHAR

## nsdl_fpi_daily
rows: 30.1k · key columns: date, known_at_utc

- `date` VARCHAR
- `asset_class` VARCHAR
- `route` VARCHAR
- `gross_purchase_cr` DOUBLE
- `gross_sales_cr` DOUBLE
- `net_cr` DOUBLE
- `net_usd_mn` DOUBLE
- `usdinr` DOUBLE
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## nse_deals
rows: 138.6k · key columns: symbol, date, known_at_utc

- `date` VARCHAR
- `deal_type` VARCHAR
- `symbol` VARCHAR
- `security` VARCHAR
- `client_name` VARCHAR
- `buy_sell` VARCHAR
- `quantity` BIGINT
- `price` DOUBLE
- `remarks` VARCHAR
- `seq` BIGINT
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## nse_insider
rows: 176.1k · key columns: symbol, known_at_utc

- `did` VARCHAR
- `pid` VARCHAR
- `symbol` VARCHAR
- `company` VARCHAR
- `acquirer_name` VARCHAR
- `person_category` VARCHAR
- `security_type` VARCHAR
- `transaction_type` VARCHAR
- `acquisition_mode` VARCHAR
- `securities_qty` DOUBLE
- `securities_value` DOUBLE
- `buy_qty` DOUBLE
- `buy_value` DOUBLE
- `sell_qty` DOUBLE
- `sell_value` DOUBLE
- `before_shares` VARCHAR
- `before_pct` VARCHAR
- `after_shares` VARCHAR
- `after_pct` VARCHAR
- `acq_from` VARCHAR
- `acq_to` VARCHAR
- `intimation_date` VARCHAR
- `disseminated_at` VARCHAR
- `exchange` VARCHAR
- `xbrl` VARCHAR
- `raw_json` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## nse_master
rows: 3.2k · key columns: isin, symbol

- `symbol` VARCHAR
- `isin` VARCHAR
- `name` VARCHAR
- `segment` VARCHAR

## nse_pit_filings
rows: 3.8k · key columns: symbol, known_at_utc

- `app_id` VARCHAR
- `segment` VARCHAR
- `symbol` VARCHAR
- `company` VARCHAR
- `regulation` VARCHAR
- `submission_type` VARCHAR
- `broadcast_at` VARCHAR
- `disseminated_at` VARCHAR
- `revision_remark` VARCHAR
- `prev_app_id` VARCHAR
- `xml_url` VARCHAR
- `ixbrl_url` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## nse_pit_xbrl_facts
rows: 157.4k · key columns: concept

- `xml_file` VARCHAR
- `context_id` VARCHAR
- `concept` VARCHAR
- `seq` BIGINT
- `value` VARCHAR
- `unit` VARCHAR

## nse_sast
rows: 37.0k · key columns: symbol, known_at_utc

- `rec_key` VARCHAR
- `symbol` VARCHAR
- `company` VARCHAR
- `acquirer_name` VARCHAR
- `sale_or_acq` VARCHAR
- `acquisition_mode` VARCHAR
- `disseminated_at` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## nse_short
rows: 45.3k · key columns: symbol, date, known_at_utc

- `date` VARCHAR
- `symbol` VARCHAR
- `security` VARCHAR
- `quantity` BIGINT
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## nse_symbol_isin
rows: 4.1k · key columns: isin, symbol

- `symbol` VARCHAR
- `isin` VARCHAR
- `first_date` DATE
- `last_date` DATE
- `src` VARCHAR

## pib_releases
rows: 28.9k · key columns: known_at_utc, doc_id, prid

- `prid` BIGINT
- `release_date` VARCHAR
- `posted_at` VARCHAR
- `ministry` VARCHAR
- `title` VARCHAR
- `relevant` BIGINT
- `fetched_at` VARCHAR
- `doc_id` BIGINT
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## pit_report
rows: 41 · key columns: table_name, n_rows, src_rows_before, src_rows_after, count_ok, copy_mode, n_with_time, n_time_unparsed

- `table_name` VARCHAR
- `n_rows` BIGINT
- `src_rows_before` BIGINT
- `src_rows_after` BIGINT
- `count_ok` BOOLEAN
- `copy_mode` VARCHAR
- `n_with_time` BIGINT
- `n_time_unparsed` BIGINT
- `min_known_at_utc` VARCHAR
- `max_known_at_utc` VARCHAR
- `seconds` DOUBLE

## policy_events
rows: 21.6k · key columns: known_at_utc, id

- `id` BIGINT
- `source_kind` VARCHAR
- `source_id` VARCHAR
- `section` BIGINT
- `published_at` VARCHAR
- `title` VARCHAR
- `policy_name` VARCHAR
- `instrument` VARCHAR
- `stage` VARCHAR
- `direction_for_industry` VARCHAR
- `sectors` VARCHAR
- `companies` VARCHAR
- `products` VARCHAR
- `amount_inr_crore` DOUBLE
- `old_value` VARCHAR
- `new_value` VARCHAR
- `unit` VARCHAR
- `effective_date` VARCHAR
- `end_date` VARCHAR
- `geography` VARCHAR
- `quote` VARCHAR
- `quote_ok` BIGINT
- `model` VARCHAR
- `extracted_at` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## price_bands
rows: 4.0M · key columns: symbol, date, known_at_utc

- `date` VARCHAR
- `symbol` VARCHAR
- `series` VARCHAR
- `band` VARCHAR
- `remarks` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## px_bse
rows: 6.8M · key columns: isin, symbol, date, sc_code

- `date` DATE
- `sc_code` VARCHAR
- `isin` VARCHAR
- `symbol` VARCHAR
- `name` VARCHAR
- `sc_group` VARCHAR
- `open` DOUBLE
- `high` DOUBLE
- `low` DOUBLE
- `close` DOUBLE
- `prev_close` DOUBLE
- `volume` BIGINT
- `value_inr` DOUBLE
- `num_trades` BIGINT
- `deliverable_qty` BIGINT
- `delivery_pct` DOUBLE
- `src` VARCHAR
- `entity_id` VARCHAR

## px_bse_adj
rows: 6.8M · key columns: isin, symbol, date, sc_code

- `date` DATE
- `sc_code` VARCHAR
- `isin` VARCHAR
- `symbol` VARCHAR
- `name` VARCHAR
- `sc_group` VARCHAR
- `open` DOUBLE
- `high` DOUBLE
- `low` DOUBLE
- `close` DOUBLE
- `prev_close` DOUBLE
- `volume` BIGINT
- `value_inr` DOUBLE
- `num_trades` BIGINT
- `deliverable_qty` BIGINT
- `delivery_pct` DOUBLE
- `src` VARCHAR
- `entity_id` VARCHAR
- `cum_price_factor` DOUBLE
- `cum_div_factor` DOUBLE
- `adj_open` DOUBLE
- `adj_high` DOUBLE
- `adj_low` DOUBLE
- `adj_close` DOUBLE
- `adj_volume` DOUBLE
- `tr_close` DOUBLE

## px_daily
rows: 7.3M · key columns: isin, symbol, date

- `exch` VARCHAR
- `entity_id` VARCHAR
- `date` DATE
- `isin` VARCHAR
- `symbol` VARCHAR
- `segment` VARCHAR
- `open` DOUBLE
- `high` DOUBLE
- `low` DOUBLE
- `close` DOUBLE
- `volume` BIGINT
- `value_inr` DOUBLE
- `deliverable_qty` BIGINT
- `delivery_pct` DOUBLE
- `cum_price_factor` DOUBLE
- `cum_div_factor` DOUBLE
- `adj_open` DOUBLE
- `adj_high` DOUBLE
- `adj_low` DOUBLE
- `adj_close` DOUBLE
- `adj_volume` DOUBLE
- `tr_close` DOUBLE

## px_nse
rows: 4.3M · key columns: isin, symbol, date

- `date` DATE
- `symbol` VARCHAR
- `series` VARCHAR
- `isin` VARCHAR
- `open` DOUBLE
- `high` DOUBLE
- `low` DOUBLE
- `close` DOUBLE
- `prev_close` DOUBLE
- `volume` BIGINT
- `value_inr` DOUBLE
- `num_trades` BIGINT
- `deliverable_qty` BIGINT
- `delivery_pct` DOUBLE
- `src` VARCHAR
- `entity_id` VARCHAR

## px_nse_adj
rows: 4.3M · key columns: isin, symbol, date

- `date` DATE
- `symbol` VARCHAR
- `series` VARCHAR
- `isin` VARCHAR
- `open` DOUBLE
- `high` DOUBLE
- `low` DOUBLE
- `close` DOUBLE
- `prev_close` DOUBLE
- `volume` BIGINT
- `value_inr` DOUBLE
- `num_trades` BIGINT
- `deliverable_qty` BIGINT
- `delivery_pct` DOUBLE
- `src` VARCHAR
- `entity_id` VARCHAR
- `cum_price_factor` DOUBLE
- `cum_div_factor` DOUBLE
- `adj_open` DOUBLE
- `adj_high` DOUBLE
- `adj_low` DOUBLE
- `adj_close` DOUBLE
- `adj_volume` DOUBLE
- `tr_close` DOUBLE

## px_primary_raw
rows: 7.3M · key columns: date

- `entity_id` VARCHAR
- `date` DATE
- `close` DOUBLE
- `open` DOUBLE
- `exch` VARCHAR
- `prev_close` DOUBLE
- `prev_date` DATE

## results_facts
rows: 13.9M · key columns: period_end, file, concept

- `file` VARCHAR
- `concept` VARCHAR
- `context` VARCHAR
- `period_start` VARCHAR
- `period_end` VARCHAR
- `instant` VARCHAR
- `value` DOUBLE
- `unit` VARCHAR
- `decimals` VARCHAR
- `period_kind` VARCHAR

## results_filings
rows: 106.6k · key columns: isin, symbol, period_end, known_at_utc, file

- `file` VARCHAR
- `taxonomy` VARCHAR
- `xbrl_url` VARCHAR
- `isin` VARCHAR
- `symbol` VARCHAR
- `scrip_code` VARCHAR
- `company` VARCHAR
- `index_period` VARCHAR
- `reporting_quarter` VARCHAR
- `consolidated` VARCHAR
- `audited` VARCHAR
- `period_start` VARCHAR
- `period_end` VARCHAR
- `fy_start` VARCHAR
- `fy_end` VARCHAR
- `board_meeting` VARCHAR
- `broadcast_ts` VARCHAR
- `dissem_ts` VARCHAR
- `filing_ts` VARCHAR
- `audit_opinion` VARCHAR
- `n_facts` BIGINT
- `status` VARCHAR
- `parsed_at` VARCHAR
- `trading_isin` VARCHAR
- `trading_isin_method` VARCHAR
- `same_issuer` BIGINT
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## results_key
rows: 106.6k · key columns: symbol, period_end, known_at_utc, file

- `file` VARCHAR
- `trading_isin` VARCHAR
- `symbol` VARCHAR
- `taxonomy` VARCHAR
- `consolidated` VARCHAR
- `audited` VARCHAR
- `period_start` VARCHAR
- `period_end` VARCHAR
- `fy_start` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR
- `RevenueFromOperations` DOUBLE
- `Income` DOUBLE
- `OtherIncome` DOUBLE
- `Expenses` DOUBLE
- `CostOfMaterialsConsumed` DOUBLE
- `EmployeeBenefitExpense` DOUBLE
- `FinanceCosts` DOUBLE
- `DepreciationDepletionAndAmortisationExpense` DOUBLE
- `ProfitBeforeExceptionalItemsAndTax` DOUBLE
- `ExceptionalItemsBeforeTax` DOUBLE
- `ProfitBeforeTax` DOUBLE
- `TaxExpense` DOUBLE
- `ProfitLossForPeriod` DOUBLE
- `ProfitOrLossAttributableToOwnersOfParent` DOUBLE
- `BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations` DOUBLE
- `DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations` DOUBLE
- `PaidUpValueOfEquityShareCapital` DOUBLE
- `FaceValueOfEquityShareCapital` DOUBLE
- `InterestEarned` DOUBLE
- `InterestExpended` DOUBLE
- `OperatingProfitBeforeProvisionAndContingencies` DOUBLE
- `ProvisionsOtherThanTaxAndContingencies` DOUBLE
- `GrossNonPerformingAssets` DOUBLE
- `NetNonPerformingAssets` DOUBLE
- `PercentageOfGrossNpa` DOUBLE
- `PercentageOfNpa` DOUBLE
- `ytd_RevenueFromOperations` DOUBLE
- `ytd_ProfitLossForPeriod` DOUBLE

## security_master
rows: 8.4k · key columns: isin, nse_symbol, bse_symbol

- `isin` VARCHAR
- `issuer` VARCHAR
- `name` VARCHAR
- `nse_symbol` VARCHAR
- `bse_code` VARCHAR
- `bse_symbol` VARCHAR
- `bse_status` VARCHAR
- `segment` VARCHAR
- `nse_listing_date` VARCHAR
- `first_trade` VARCHAR
- `last_trade` VARCHAR
- `last_seen_nse` VARCHAR
- `last_seen_bse` VARCHAR
- `in_master_companies` BIGINT
- `source` VARCHAR

## shp_index
rows: 50.8k · key columns: isin, symbol, known_at_utc, file

- `record_id` VARCHAR
- `idx` VARCHAR
- `symbol` VARCHAR
- `isin` VARCHAR
- `name` VARCHAR
- `quarter_end` VARCHAR
- `broadcast_at` VARCHAR
- `submission_date` VARCHAR
- `promoter_pct` DOUBLE
- `public_pct` DOUBLE
- `revised` VARCHAR
- `xbrl` VARCHAR
- `file` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## snapshot_meta
rows: 1 · key columns: snapshot_date, built_from, built_to, report_json

- `snapshot_date` VARCHAR
- `built_from` TIMESTAMP
- `built_to` TIMESTAMP
- `report_json` VARCHAR

## symbol_isin_history
rows: 9.4k · key columns: isin, symbol

- `exchange` VARCHAR
- `symbol` VARCHAR
- `isin` VARCHAR
- `first_date` VARCHAR
- `last_date` VARCHAR
- `n_days` BIGINT

## tax_rules
rows: 20 · key columns: rule, value, effective_from, effective_to, basis, announced_at, policy_event_ids, source_title

- `rule` VARCHAR
- `value` DOUBLE
- `effective_from` VARCHAR
- `effective_to` VARCHAR
- `basis` VARCHAR
- `announced_at` VARCHAR
- `policy_event_ids` VARCHAR
- `source_title` VARCHAR
- `source_url` VARCHAR
- `source_file` VARCHAR
- `source_page` BIGINT
- `quote` VARCHAR
- `quote_verified` BIGINT
- `note` VARCHAR
- `built_at` VARCHAR

## tg_company_mentions
rows: 261 · key columns: isin, symbol, known_at_utc

- `topic_id` BIGINT
- `post_id` VARCHAR
- `message_id` BIGINT
- `post_ts_utc` VARCHAR
- `symbol` VARCHAR
- `isin` VARCHAR
- `source` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## tg_order_schedule
rows: 1.0k · key columns: isin

- `order_id` VARCHAR
- `isin` VARCHAR
- `fy` BIGINT
- `q` BIGINT
- `amount_cr` DOUBLE

## tg_orders
rows: 219 · key columns: isin, symbol, known_at_utc, known_at

- `order_id` VARCHAR
- `post_id` VARCHAR
- `message_id` BIGINT
- `kind` VARCHAR
- `isin` VARCHAR
- `symbol` VARCHAR
- `company` VARCHAR
- `customer` VARCHAR
- `description` VARCHAR
- `value_cr` DOUBLE
- `annual_cr` DOUBLE
- `duration_months` DOUBLE
- `duration_source` VARCHAR
- `revenue_cr` DOUBLE
- `revenue_fy` VARCHAR
- `pct_of_revenue` DOUBLE
- `mcap_cr` DOUBLE
- `price_at_alert` DOUBLE
- `known_at` VARCHAR
- `known_at_source` VARCHAR
- `post_ts_utc` VARCHAR
- `filing_url` VARCHAR
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## tg_pead_signals
rows: 731 · key columns: isin, symbol, known_at_utc

- `post_id` VARCHAR
- `message_id` BIGINT
- `post_ts_utc` VARCHAR
- `company_text` VARCHAR
- `label` VARCHAR
- `symbol` VARCHAR
- `isin` VARCHAR
- `symbol_source` VARCHAR
- `filing_url` VARCHAR
- `screener_url` VARCHAR
- `is_test_post` BIGINT
- `known_at_src` VARCHAR
- `known_at_utc` TIMESTAMP
- `known_at_precision` VARCHAR

## truth_report
rows: 1 · key columns: report_json

- `report_json` VARCHAR

## unexplained_jumps
rows: 1.2k · key columns: date

- `entity_id` VARCHAR
- `date` TIMESTAMP
- `prev_date` TIMESTAMP
- `prev_close` DOUBLE
- `open` DOUBLE
- `close` DOUBLE
- `exch` VARCHAR
- `r` DOUBLE
- `clean_ratio` DOUBLE
