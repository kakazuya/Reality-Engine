# equity_intelligence schema

File: `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\equity_intelligence.db` (50.1 GB)

Live primary equity database: company master, normalized daily prices, financials, corporate actions/documents, ownership/market flows, policy/macro/ripple layers, substrate analytics, Telegram signals and quarantine. Use it for latest/live data and full text; use truth_duckdb for adjusted price history and PIT-stamped research tables. Mixed raw and derived; check per-table notes.

## amfi_months
rows: ~95 · key columns: month

- `month` TEXT
- `rows` INTEGER
- `fetched_at` TEXT

## annual_financials
rows: 12.9k · key columns: isin, symbol, fiscal_year

- `id` INTEGER
- `isin` TEXT
- `symbol` TEXT
- `fiscal_year` TEXT
- `revenue_inr_cr` REAL
- `ebitda_inr_cr` REAL
- `net_profit_inr_cr` REAL
- `eps_inr` REAL
- `opm_pct` REAL
- `npm_pct` REAL
- `roce_pct` REAL
- `roe_pct` REAL
- `debt_inr_cr` REAL
- `equity_inr_cr` REAL
- `debt_to_equity` REAL
- `interest_coverage` REAL
- `operating_cash_flow_inr_cr` REAL
- `free_cash_flow_inr_cr` REAL
- `created_at` TIMESTAMP
- `source` TEXT

## ar_doc_identity
rows: ~140.0k · key columns: doc_id

- `doc_id` INTEGER
- `verdict` TEXT
- `true_company` TEXT
- `true_isin` TEXT
- `evidence` TEXT
- `checked_by` TEXT
- `checked_at` TEXT

## ar_doc_scan
rows: ~140.7k · key columns: doc_id

- `doc_id` INTEGER
- `verdict` TEXT
- `reason` TEXT
- `scanned_at` TEXT

## board_meetings
rows: ~122.8k · key columns: symbol, isin, meeting_date

- `symbol` TEXT
- `isin` TEXT
- `idx` TEXT
- `meeting_date` TEXT
- `purpose` TEXT
- `description` TEXT
- `intimated_at` TEXT
- `industry` TEXT
- `attachment` TEXT
- `fetched_at` TEXT

## bse_annual_reports
rows: ~76.3k · key columns: scripcode, file_key, year

- `scripcode` TEXT
- `year` TEXT
- `file_name` TEXT
- `file_key` TEXT
- `dt_tm` TEXT
- `fetched_at` TEXT

## bse_annual_reports_fetch
rows: ~12.9k · key columns: scripcode

- `scripcode` TEXT
- `status` INTEGER
- `n` INTEGER
- `fetched_at` TEXT

## bulk_block_deals
rows: ~228 · key columns: id, deal_date, symbol

- `id` TEXT
- `deal_date` DATE
- `symbol` TEXT
- `client_name` TEXT
- `deal_type` TEXT
- `buy_sell` TEXT
- `quantity` INTEGER
- `trade_price` REAL
- `is_marquee_institution` BOOLEAN
- `created_at` TIMESTAMP

## business_model_profiles
rows: ~6.4k · key columns: isin, symbol, company_id

- `company_id` INTEGER
- `isin` TEXT
- `symbol` TEXT
- `archetype` TEXT
- `revenue_recurrence_pct` REAL
- `pricing_power_score` INTEGER
- `capital_intensity_score` INTEGER
- `operating_leverage_score` INTEGER
- `qualitative_notes` TEXT
- `updated_at` TEXT

## chunk_symbol_tags
rows: ~194 · key columns: chunk_id, symbol

- `chunk_id` INTEGER
- `symbol` TEXT
- `isin` TEXT
- `score` REAL
- `method` TEXT

## circuit_hits
rows: ~282.2k · key columns: date, symbol, series

- `date` TEXT
- `symbol` TEXT
- `series` TEXT
- `high_low` TEXT

## company_business_features
rows: ~1.0k · key columns: symbol

- `symbol` TEXT
- `chunks` INTEGER
- `sources_json` TEXT
- `centroid_norm` REAL
- `terms_json` TEXT
- `quarantined` INTEGER
- `features_version` TEXT
- `computed_at` TEXT

## company_business_graph
rows: ~20.6k · key columns: anchor_symbol, peer_symbol

- `anchor_symbol` TEXT
- `peer_symbol` TEXT
- `rank` INTEGER
- `similarity` REAL
- `shared_terms_json` TEXT
- `source_mix_json` TEXT
- `anchor_chunks` INTEGER
- `peer_chunks` INTEGER
- `features_version` TEXT
- `computed_at` TEXT

## company_business_runs
rows: ~4 · key columns: run_id

- `run_id` INTEGER
- `status` TEXT
- `reason` TEXT
- `n_symbols` INTEGER
- `n_chunks` INTEGER
- `n_pairs` INTEGER
- `min_chunks` INTEGER
- `top_k` INTEGER
- `computed_at` TEXT

## company_distilled_parameters
rows: ~17.7k · key columns: isin, parameter_key

- `isin` TEXT
- `symbol` TEXT
- `parameter_key` TEXT
- `value_json` TEXT
- `confidence_score` REAL
- `source_document_ref` TEXT
- `last_updated_date` DATE

## company_entity_edges
rows: ~73.5k · key columns: src_symbol, dst_kind, dst_key, edge_family

- `src_symbol` TEXT
- `dst_kind` TEXT
- `dst_key` TEXT
- `edge_family` TEXT
- `weight` REAL
- `evidence_json` TEXT

## company_forensic_health
rows: ~4.3k · key columns: isin, symbol

- `isin` TEXT
- `symbol` TEXT
- `fiscal_year` TEXT
- `promoter_holding_pct` REAL
- `promoter_pledge_pct` REAL
- `fii_holding_pct` REAL
- `dii_holding_pct` REAL
- `public_holding_pct` REAL
- `interest_coverage_ratio` REAL
- `debt_to_equity_ratio` REAL
- `market_cap_inr_cr` REAL
- `pe_ratio` REAL
- `pb_ratio` REAL
- `dividend_yield_pct` REAL
- `altman_z_score` REAL
- `auditor_name` TEXT
- `has_qualified_audit_opinion` BOOLEAN
- `related_party_tx_pct_revenue` REAL
- `is_solvency_approved` BOOLEAN
- `solvency_disqualification_reasons` TEXT
- `last_evaluated_date` DATE

## company_industry
rows: ~2.1k · key columns: symbol, isin

- `isin` TEXT
- `symbol` TEXT
- `series` TEXT
- `macro` TEXT
- `sector` TEXT
- `industry` TEXT
- `basic_industry` TEXT
- `index_list` TEXT
- `listing_date` TEXT
- `fetched_at` TEXT

## company_peer_features
rows: ~5.0k · key columns: symbol

- `symbol` TEXT
- `features_json` TEXT
- `present` INTEGER
- `total` INTEGER
- `quarantined` INTEGER
- `features_version` TEXT
- `computed_at` TEXT
- `baseline_similarity` REAL

## company_peer_graph
rows: ~51.5k · key columns: anchor_symbol, peer_symbol

- `anchor_symbol` TEXT
- `peer_symbol` TEXT
- `rank` INTEGER
- `similarity` REAL
- `coverage` REAL
- `shared_features` INTEGER
- `drivers_json` TEXT
- `features_version` TEXT
- `computed_at` TEXT
- `shared_families` INTEGER

## company_peer_runs
rows: ~10 · key columns: run_id

- `run_id` INTEGER
- `status` TEXT
- `reason` TEXT
- `n_symbols` INTEGER
- `n_active_features` INTEGER
- `active_features_json` TEXT
- `dropped_features_json` TEXT
- `top_k` INTEGER
- `computed_at` TEXT
- `diagnostics_json` TEXT

## corporate_actions
rows: ~27.6k · key columns: isin, symbol, ex_date, action_type

- `id` INTEGER
- `isin` TEXT
- `symbol` TEXT
- `company_name` TEXT
- `subject` TEXT
- `action_type` TEXT
- `ex_date` DATE
- `rec_date` DATE
- `bc_start_date` DATE
- `bc_end_date` DATE
- `nd_start_date` DATE
- `nd_end_date` DATE
- `broadcast_date` DATE
- `face_value` REAL
- `series` TEXT
- `industry` TEXT
- `source` TEXT
- `fetched_at` TIMESTAMP

## corporate_documents
rows: 127.2k · key columns: id, isin, symbol, doc_type

- `id` INTEGER
- `isin` TEXT
- `symbol` TEXT
- `doc_type` TEXT
- `title` TEXT
- `doc_date` DATE
- `source_url` TEXT
- `local_file_path` TEXT
- `file_size_bytes` INTEGER
- `sha256_hash` TEXT
- `is_processed` BOOLEAN
- `created_at` TIMESTAMP
- `source` TEXT
- `discovery_source` TEXT
- `event_date` TEXT
- `event_source` TEXT
- `doc_version` INTEGER
- `call_date` TEXT
- `publication_date` TEXT
- `pit_source` TEXT
- `pit_tier` INTEGER
- `pit_applied_at` TEXT
- `bse_newsid` TEXT
- `bse_dissem_ts` TEXT
- `bse_news_dt` TEXT
- `bse_subcat` TEXT
- `bse_joined_at` TEXT
- `fiscal_period_end` TEXT

## corporate_status_flags
rows: 0 · key columns: symbol, status_type, source

- `id` INTEGER
- `isin` TEXT
- `symbol` TEXT
- `status_type` TEXT
- `source` TEXT
- `detail` TEXT
- `detected_at` TIMESTAMP

## countries
rows: ~4 · key columns: country_id

- `country_id` VARCHAR(3)
- `country_name` VARCHAR(100)
- `political_stability_score` NUMERIC(3,2)
- `rule_of_law_index` NUMERIC(3,2)
- `currency` VARCHAR(10)

## daily_price_delivery
rows: 3.1M · key columns: date, symbol, isin

- `date` DATE
- `symbol` TEXT
- `isin` TEXT
- `series` TEXT
- `open` REAL
- `high` REAL
- `low` REAL
- `close` REAL
- `prev_close` REAL
- `change_pct` REAL
- `total_volume` INTEGER
- `turnover_lacs` REAL
- `num_trades` INTEGER
- `deliverable_volume` INTEGER
- `delivery_pct` REAL
- `delivery_spike_ratio` REAL
- `delivery_conviction_score` REAL
- `sma_20` REAL
- `sma_50` REAL
- `sma_200` REAL
- `rsi_14` REAL
- `high_52w` REAL
- `low_52w` REAL
- `distance_from_52w_high_pct` REAL

## distillation_runs
rows: ~6 · key columns: run_id

- `run_id` INTEGER
- `run_date` TEXT
- `source_type` TEXT
- `chunks_distilled` INTEGER
- `vectors_purged` INTEGER
- `summary` TEXT
- `moat_updates` TEXT

## document_chunks
rows: 2.3M · key columns: chunk_id, doc_id, isin, symbol

- `chunk_id` INTEGER
- `doc_id` INTEGER
- `chunk_index` INTEGER
- `content` TEXT
- `embedding` TEXT
- `published_date` TEXT
- `timestamp_start_sec` INTEGER
- `timestamp_end_sec` INTEGER
- `sector_id` INTEGER
- `industry_id` INTEGER
- `symbol` TEXT
- `isin` TEXT
- `fiscal_period` TEXT
- `fiscal_confidence` REAL
- `fiscal_source` TEXT
- `event_date` TEXT
- `event_source` TEXT
- `doc_version` INTEGER

## dynamic_parameter_definitions
rows: ~5 · key columns: parameter_key

- `parameter_key` TEXT
- `display_name` TEXT
- `data_type` TEXT
- `description` TEXT
- `category` TEXT
- `created_at` TIMESTAMP

## entity_graph_runs
rows: ~1 · key columns: run_id

- `run_id` INTEGER
- `status` TEXT
- `reason` TEXT
- `n_src_symbols` INTEGER
- `n_edges` INTEGER
- `families_json` TEXT
- `computed_at` TEXT

## eod_correction_log
rows: ~57 · key columns: correction_id, target_date

- `correction_id` INTEGER
- `correction_type` TEXT
- `universe` TEXT
- `target_date` TEXT
- `symbols_corrected` INTEGER
- `noise_floors_updated` INTEGER
- `lens_rank_changes` INTEGER
- `event_id` TEXT
- `details_json` TEXT
- `created_at` TEXT

## eod_scrip_calls
rows: ~5.5k · key columns: date, symbol, isin

- `date` DATE
- `symbol` TEXT
- `isin` TEXT
- `composite_rank` INTEGER
- `technical_score` REAL
- `fundamental_score` REAL
- `alt_sentiment_score` REAL
- `composite_score` REAL
- `current_market_price` REAL
- `recommended_entry_range` TEXT
- `target_price` REAL
- `stop_loss` REAL
- `risk_reward_ratio` REAL
- `conviction_level` TEXT
- `is_solvency_approved` BOOLEAN
- `delivery_spike_ratio` REAL
- `delivery_conviction_score` REAL
- `yoy_revenue_growth_pct` REAL
- `yoy_pat_growth_pct` REAL
- `created_at` TIMESTAMP

## etf_inav
rows: ~6.8k · key columns: isin, date

- `isin` TEXT
- `date` TEXT
- `underlying` TEXT
- `idx_close` REAL
- `idx_date` TEXT
- `fx` REAL
- `k` REAL
- `inav` REAL
- `close` REAL
- `nav` REAL
- `premium_vs_inav_pct` REAL

## etf_master
rows: ~432 · key columns: isin

- `isin` TEXT
- `symbol` TEXT
- `first_date` TEXT
- `last_date` TEXT
- `n_days` INTEGER
- `scheme_code` TEXT
- `scheme_name` TEXT

## etf_premium
rows: 267.6k · key columns: isin, symbol, date

- `isin` TEXT
- `symbol` TEXT
- `date` TEXT
- `close` REAL
- `nav` REAL
- `premium_pct`
- `value_inr` REAL

## etf_px
rows: ~313.8k · key columns: date, symbol, isin

- `date` TEXT
- `symbol` TEXT
- `isin` TEXT
- `close` REAL
- `volume` REAL
- `value_inr` REAL
- `source` TEXT

## financial_metrics
rows: ~2.6k · key columns: company_id, isin, symbol, fiscal_year

- `company_id` INTEGER
- `isin` TEXT
- `symbol` TEXT
- `fiscal_year` INTEGER
- `roic` REAL
- `wacc` REAL
- `roic_wacc_spread` REAL
- `fcf_margin` REAL
- `debt_to_ebitda` REAL
- `gross_margin_peer_percentile` INTEGER

## financially_free_breadth
rows: 0 · key columns: date, sector_name

- `date` DATE
- `sector_name` TEXT
- `advances_count` INTEGER
- `declines_count` INTEGER
- `advance_decline_ratio` REAL
- `sector_momentum_score` REAL
- `top_gainers_json` TEXT
- `top_losers_json` TEXT
- `created_at` TIMESTAMP

## forecast_skill_history
rows: ~158 · key columns: round_id

- `round_id` INTEGER
- `mode` TEXT
- `horizon_days` INTEGER
- `train_from` TEXT
- `train_to` TEXT
- `eval_from` TEXT
- `eval_to` TEXT
- `n_train_dates` INTEGER
- `n_eval_dates` INTEGER
- `weights_json` TEXT
- `weight_stats_json` TEXT
- `edge_uniform` REAL
- `edge_weighted` REAL
- `eval_ic` REAL
- `applied` INTEGER
- `notes` TEXT
- `created_at` TEXT

## fund_nav
rows: ~329.5k · key columns: isin, date

- `isin` TEXT
- `date` TEXT
- `nav` REAL
- `scheme_code` TEXT
- `scheme_name` TEXT

## geographic_exposure
rows: ~3.6k · key columns: company_id, country_id

- `company_id` INTEGER
- `country_id` TEXT
- `revenue_share_pct` REAL
- `asset_exposure_pct` REAL
- `created_at` TEXT

## graph_causal_edges
rows: ~15 · key columns: edge_id, source_node_id, target_node_id

- `edge_id` TEXT
- `source_node_id` TEXT
- `target_node_id` TEXT
- `relationship_type` TEXT
- `impact_direction` TEXT
- `elasticity_score` REAL
- `transmission_mechanism` TEXT
- `evidence_document_ref` TEXT
- `confidence_score` REAL
- `created_at` TIMESTAMP

## graph_nodes
rows: ~19 · key columns: node_id

- `node_id` TEXT
- `node_type` TEXT
- `name` TEXT
- `metadata_json` TEXT
- `created_at` TIMESTAMP

## inbox_ingestion_manifest
rows: ~343 · key columns: file_hash

- `file_hash` TEXT
- `original_filename` TEXT
- `file_type` TEXT
- `detected_entity_type` TEXT
- `target_entity_key` TEXT
- `summary` TEXT
- `extracted_parameters_json` TEXT
- `associated_graph_nodes_json` TEXT
- `processed_file_path` TEXT
- `ingested_timestamp` TIMESTAMP

## index_membership
rows: ~300 · key columns: index_name, symbol

- `index_name` TEXT
- `symbol` TEXT
- `isin` TEXT
- `company_name` TEXT
- `industry` TEXT
- `as_of` TEXT
- `source` TEXT

## index_tri
rows: ~19.3k · key columns: index_name, date

- `index_name` TEXT
- `date` TEXT
- `tri` REAL
- `price` REAL
- `source` TEXT
- `method` TEXT
- `fetched_at` TEXT

## industries
rows: ~12 · key columns: industry_id, industry_name

- `industry_id` INTEGER
- `sector_name` TEXT
- `industry_name` TEXT
- `secular_growth_score` REAL
- `lifecycle_stage` TEXT
- `tam_growth_cagr` REAL

## insider_trades
rows: 0 · key columns: id, symbol, isin

- `id` TEXT
- `symbol` TEXT
- `isin` TEXT
- `acquirer_name` TEXT
- `category_of_person` TEXT
- `transaction_type` TEXT
- `num_shares` INTEGER
- `value_inr_lacs` REAL
- `mode_of_acquisition` TEXT
- `acquisition_date` DATE
- `intimation_date` DATE

## intelligence_fts
rows: 2.3M · key columns: rowid, chunk_id, symbol, isin

- `chunk_id`
- `symbol`
- `isin`
- `source_type`
- `document_date`
- `document_text`

## isin_rekey_log
rows: ~7.8k · key columns: db, table_name, symbol

- `db` TEXT
- `table_name` TEXT
- `symbol` TEXT
- `old_isin` TEXT
- `new_isin` TEXT
- `n_rows` INTEGER
- `ts` TEXT

## lens_activation_log
rows: ~1.1k · key columns: log_id

- `log_id` INTEGER
- `temperature` REAL
- `fired_lenses` TEXT
- `context_json` TEXT
- `created_at` TEXT

## macro_events
rows: ~30 · key columns: event_id, event_date

- `event_id` TEXT
- `event_name` TEXT
- `category` TEXT
- `event_date` DATE
- `raw_document_path` TEXT
- `summary` TEXT
- `affected_nodes_json` TEXT
- `created_at` TIMESTAMP
- `doc_id` INTEGER

## master_companies
rows: ~6.8k · key columns: isin, nse_symbol, bse_code

- `isin` TEXT
- `nse_symbol` TEXT
- `bse_code` TEXT
- `company_name` TEXT
- `industry` TEXT
- `sector` TEXT
- `market_cap_tier` TEXT
- `is_fno_eligible` BOOLEAN
- `is_nifty50` BOOLEAN
- `is_nifty100` BOOLEAN
- `is_nifty200` BOOLEAN
- `is_nifty500` BOOLEAN
- `is_active` BOOLEAN
- `created_at` TIMESTAMP
- `updated_at` TIMESTAMP
- `listing_source` TEXT
- `is_screenable` INTEGER

## mkt_bse_deals
rows: ~135.5k · key columns: date, deal_type, sc_code

- `date` TEXT
- `deal_type` TEXT
- `sc_code` TEXT
- `scrip_name` TEXT
- `client_name` TEXT
- `buy_sell` TEXT
- `quantity` REAL
- `price` REAL
- `seq` INTEGER

## mkt_bse_delivery_daily
rows: ~7.5M · key columns: date, sc_code

- `date` TEXT
- `sc_code` TEXT
- `deliverable_qty` INTEGER
- `deliverable_value` REAL
- `volume` INTEGER
- `turnover_inr` REAL
- `delivery_pct` REAL

## mkt_bse_eq_daily
rows: ~7.5M · key columns: date, sc_code, isin

- `date` TEXT
- `sc_code` TEXT
- `isin` TEXT
- `symbol` TEXT
- `name` TEXT
- `sc_group` TEXT
- `sc_type` TEXT
- `open` REAL
- `high` REAL
- `low` REAL
- `close` REAL
- `last` REAL
- `prev_close` REAL
- `num_trades` INTEGER
- `volume` INTEGER
- `turnover_inr` REAL
- `file_format` TEXT

## mkt_bse_index_daily
rows: ~143.6k · key columns: date, index_code

- `date` TEXT
- `index_code` TEXT
- `index_name` TEXT
- `open` REAL
- `high` REAL
- `low` REAL
- `close` REAL
- `prev_close` REAL
- `pe` REAL
- `pb` REAL
- `div_yield` REAL
- `turnover` TEXT
- `shares_traded` TEXT

## mkt_bse_insider
rows: ~153.9k · key columns: file, line_no, isin

- `file` TEXT
- `line_no` INTEGER
- `company` TEXT
- `isin` TEXT
- `person` TEXT
- `raw_json` TEXT

## mkt_commodity_daily
rows: ~25.3k · key columns: date, commodity

- `date` TEXT
- `commodity` TEXT
- `ticker` TEXT
- `open` REAL
- `high` REAL
- `low` REAL
- `close` REAL
- `adj_close` REAL
- `volume` REAL
- `source` TEXT

## mkt_commodity_monthly
rows: ~9.2k · key columns: month, series

- `month` TEXT
- `series` TEXT
- `unit` TEXT
- `value` REAL
- `source` TEXT

## mkt_fii_dii_cash
rows: ~1.9k · key columns: date

- `date` TEXT
- `fii_purchase_cr` REAL
- `fii_sales_cr` REAL
- `fii_net_cr` REAL
- `dii_purchase_cr` REAL
- `dii_sales_cr` REAL
- `dii_net_cr` REAL
- `nifty_close` REAL
- `nifty_prev_close` REAL
- `nifty_change_pct` REAL
- `source` TEXT

## mkt_load_log
rows: ~25.1k · key columns: source, file

- `source` TEXT
- `file` TEXT
- `rows` INTEGER
- `loaded_at` TEXT

## mkt_nsdl_fpi_daily
rows: ~33.1k · key columns: date, asset_class, route

- `date` TEXT
- `asset_class` TEXT
- `route` TEXT
- `gross_purchase_cr` REAL
- `gross_sales_cr` REAL
- `net_cr` REAL
- `net_usd_mn` REAL
- `usdinr` REAL

## mkt_nse_deals
rows: ~138.6k · key columns: date, deal_type, symbol

- `date` TEXT
- `deal_type` TEXT
- `symbol` TEXT
- `security` TEXT
- `client_name` TEXT
- `buy_sell` TEXT
- `quantity` INTEGER
- `price` REAL
- `remarks` TEXT
- `seq` INTEGER

## mkt_nse_eq_daily
rows: ~1.4M · key columns: date, symbol, series

- `date` TEXT
- `symbol` TEXT
- `series` TEXT
- `isin` TEXT
- `open` REAL
- `high` REAL
- `low` REAL
- `close` REAL
- `last` REAL
- `prev_close` REAL
- `volume` INTEGER
- `turnover_inr` REAL
- `num_trades` INTEGER
- `deliverable_qty` INTEGER
- `delivery_pct` REAL

## mkt_nse_full_daily
rows: ~4.5M · key columns: date, symbol, series

- `date` TEXT
- `symbol` TEXT
- `series` TEXT
- `prev_close` REAL
- `open` REAL
- `high` REAL
- `low` REAL
- `last` REAL
- `close` REAL
- `avg_price` REAL
- `volume` INTEGER
- `turnover_lacs` REAL
- `num_trades` INTEGER
- `deliverable_qty` INTEGER
- `delivery_pct` REAL

## mkt_nse_index_daily
rows: ~205.9k · key columns: date, index_name

- `date` TEXT
- `index_name` TEXT
- `open` REAL
- `high` REAL
- `low` REAL
- `close` REAL
- `points_change` REAL
- `pct_change` REAL
- `volume` INTEGER
- `turnover_cr` REAL
- `pe` REAL
- `pb` REAL
- `div_yield` REAL

## mkt_nse_insider
rows: ~176.9k · key columns: did, pid, symbol

- `did` TEXT
- `pid` TEXT
- `symbol` TEXT
- `company` TEXT
- `acquirer_name` TEXT
- `person_category` TEXT
- `security_type` TEXT
- `transaction_type` TEXT
- `acquisition_mode` TEXT
- `securities_qty` REAL
- `securities_value` REAL
- `buy_qty` REAL
- `buy_value` REAL
- `sell_qty` REAL
- `sell_value` REAL
- `before_shares` TEXT
- `before_pct` TEXT
- `after_shares` TEXT
- `after_pct` TEXT
- `acq_from` TEXT
- `acq_to` TEXT
- `intimation_date` TEXT
- `disseminated_at` TEXT
- `exchange` TEXT
- `xbrl` TEXT
- `raw_json` TEXT

## mkt_nse_participant
rows: ~19.2k · key columns: date, kind, client_type

- `date` TEXT
- `kind` TEXT
- `client_type` TEXT
- `fut_idx_long` REAL
- `fut_idx_short` REAL
- `fut_stk_long` REAL
- `fut_stk_short` REAL
- `opt_idx_call_long` REAL
- `opt_idx_put_long` REAL
- `opt_idx_call_short` REAL
- `opt_idx_put_short` REAL
- `opt_stk_call_long` REAL
- `opt_stk_put_long` REAL
- `opt_stk_call_short` REAL
- `opt_stk_put_short` REAL
- `total_long` REAL
- `total_short` REAL

## mkt_nse_pit_filings
rows: ~3.9k · key columns: app_id, segment

- `app_id` TEXT
- `segment` TEXT
- `symbol` TEXT
- `company` TEXT
- `regulation` TEXT
- `submission_type` TEXT
- `broadcast_at` TEXT
- `disseminated_at` TEXT
- `revision_remark` TEXT
- `prev_app_id` TEXT
- `xml_url` TEXT
- `ixbrl_url` TEXT

## mkt_nse_pit_xbrl_facts
rows: ~157.1k · key columns: xml_file, context_id, concept

- `xml_file` TEXT
- `context_id` TEXT
- `concept` TEXT
- `seq` INTEGER
- `value` TEXT
- `unit` TEXT

## mkt_nse_sast
rows: ~37.1k · key columns: rec_key, symbol

- `rec_key` TEXT
- `symbol` TEXT
- `company` TEXT
- `acquirer_name` TEXT
- `sale_or_acq` TEXT
- `acquisition_mode` TEXT
- `disseminated_at` TEXT
- `raw_json` TEXT

## mkt_nse_short
rows: ~45.5k · key columns: date, symbol

- `date` TEXT
- `symbol` TEXT
- `security` TEXT
- `quantity` INTEGER

## mkt_nse_sme_daily
rows: ~254.2k · key columns: date, symbol, series

- `date` TEXT
- `symbol` TEXT
- `series` TEXT
- `security` TEXT
- `open` REAL
- `high` REAL
- `low` REAL
- `close` REAL
- `prev_close` REAL
- `volume` INTEGER
- `turnover_inr` REAL
- `corp_ind` TEXT
- `high_52w` REAL
- `low_52w` REAL

## mkt_report_cells
rows: ~528.5k · key columns: source, file, table_idx, row_idx, col_idx

- `source` TEXT
- `file` TEXT
- `table_idx` INTEGER
- `row_idx` INTEGER
- `col_idx` INTEGER
- `value` TEXT

## moat_evaluations
rows: ~6.4k · key columns: company_id, ticker, isin

- `company_id` INTEGER
- `ticker` TEXT
- `eval_date` TEXT
- `switching_costs` INTEGER
- `network_effects` INTEGER
- `cost_advantage` INTEGER
- `intangible_assets` INTEGER
- `efficient_scale` INTEGER
- `total_moat_score` REAL
- `moat_width` TEXT
- `moat_trajectory` TEXT
- `isin` TEXT

## moat_history
rows: ~71.6k · key columns: symbol, asof_date

- `history_id` INTEGER
- `symbol` TEXT
- `asof_date` TEXT
- `moat_score` REAL
- `moat_width` TEXT
- `trajectory` TEXT
- `source` TEXT
- `created_at` TEXT

## model_explainer_rankings
rows: ~95.0k · key columns: stock_id, sector_id, geo_id, regime_tag, investor_majority, lens_family

- `ranking_id` INTEGER
- `stock_id` TEXT
- `sector_id` TEXT
- `geo_id` TEXT
- `regime_tag` TEXT
- `investor_majority` TEXT
- `lens_family` TEXT
- `p_value` REAL
- `explain_power` REAL
- `rank` INTEGER
- `created_at` TEXT

## model_lens_weight_proposals
rows: ~28 · key columns: proposal_id, regime_tag, investor_majority, lens_family

- `proposal_id` INTEGER
- `regime_tag` TEXT
- `investor_majority` TEXT
- `lens_family` TEXT
- `weight` REAL
- `basis_json` TEXT
- `created_at` TEXT

## model_validation_scores
rows: ~40.0k · key columns: asof_date, horizon_days, mode, lens_family

- `score_id` INTEGER
- `asof_date` DATE
- `horizon_days` INTEGER
- `mode` TEXT
- `lens_family` TEXT
- `regime_tag` TEXT
- `investor_majority` TEXT
- `n` INTEGER
- `hit_rate` REAL
- `mean_fwd_ret` REAL
- `universe_mean_ret` REAL
- `ic` REAL
- `thesis_hit_rate` REAL
- `thesis_n` INTEGER
- `created_at` TEXT

## move_attribution
rows: ~167.9k · key columns: symbol, attribution_date

- `attribution_id` INTEGER
- `symbol` TEXT
- `attribution_date` TEXT
- `realized_move_pct` REAL
- `noise_floor` REAL
- `is_material` INTEGER
- `explained_total` REAL
- `residual` REAL
- `lens_factor_statistical_dir` INTEGER
- `lens_business_quality_dir` INTEGER
- `lens_policy_macro_dir` INTEGER
- `lens_supply_chain_dir` INTEGER
- `lens_factor_statistical_w` REAL
- `lens_business_quality_w` REAL
- `lens_policy_macro_w` REAL
- `lens_supply_chain_w` REAL
- `lens_factor_statistical_share` REAL
- `lens_business_quality_share` REAL
- `lens_policy_macro_share` REAL
- `lens_supply_chain_share` REAL
- `investor_majority` TEXT
- `regime_tag` TEXT

## news_visual_artifacts
rows: ~52 · key columns: artifact_id, doc_id, symbol

- `artifact_id` INTEGER
- `doc_id` INTEGER
- `symbol` TEXT
- `source_type` TEXT
- `source_url` TEXT
- `media_url` TEXT
- `local_path` TEXT
- `ocr_text` TEXT
- `ocr_confidence` REAL
- `ocr_chars` INTEGER
- `created_at` TIMESTAMP

## noise_floors
rows: ~201 · key columns: symbol

- `symbol` TEXT
- `floor` REAL
- `realized_vol` REAL
- `liquidity` REAL
- `sample_days` INTEGER
- `learned_at` TEXT

## nse_index_breadth
rows: ~5.0k · key columns: date, index_name

- `date` DATE
- `index_name` TEXT
- `open` REAL
- `high` REAL
- `low` REAL
- `close` REAL
- `change_pct` REAL
- `points_change` REAL
- `volume` INTEGER
- `turnover_cr` REAL
- `advances_count` INTEGER
- `declines_count` INTEGER
- `advance_decline_ratio` REAL
- `pe_ratio` REAL
- `pb_ratio` REAL
- `dividend_yield` REAL

## nse_pr_days
rows: ~783 · key columns: date

- `date` TEXT
- `pr` INTEGER
- `sec_list` INTEGER
- `done_at` TEXT

## pc_restore_doc_links
rows: ~63.8k · key columns: source_table, prid

- `source_table` TEXT
- `prid` INTEGER
- `pc_doc_id` INTEGER
- `local_doc_id` INTEGER
- `restore_source` TEXT

## pib_days
rows: ~1.8k · key columns: day

- `day` TEXT
- `n` INTEGER
- `done_at` TEXT

## pib_ml_days
rows: ~1.2k · key columns: day, reg, lang

- `day` TEXT
- `reg` INTEGER
- `lang` INTEGER
- `n` INTEGER
- `done_at` TEXT

## pib_ml_langs
rows: ~62 · key columns: reg, lang

- `reg` INTEGER
- `reg_name` TEXT
- `lang` INTEGER
- `lang_name` TEXT

## pib_ml_match
rows: ~14.4k · key columns: prid, mode

- `prid` INTEGER
- `mode` TEXT
- `best_prid` INTEGER
- `best_sim` REAL
- `second_sim` REAL
- `n_candidates` INTEGER
- `matched_at` TEXT

## pib_ml_releases
rows: ~2.3M · key columns: prid, doc_id

- `prid` INTEGER
- `release_date` TEXT
- `reg` INTEGER
- `lang` INTEGER
- `lang_name` TEXT
- `ministry` TEXT
- `title` TEXT
- `posted_at` TEXT
- `posted_by` TEXT
- `body` TEXT
- `linked_prid` INTEGER
- `translation_of` INTEGER
- `match_method` TEXT
- `match_sim` REAL
- `fetched_at` TEXT
- `doc_id` INTEGER

## pib_ml_releases_fts
rows: ~2.3M · key columns: rowid

- `title`
- `body`
- `ministry`

## pib_releases
rows: ~2.3M · key columns: prid, doc_id

- `prid` INTEGER
- `release_date` TEXT
- `posted_at` TEXT
- `ministry` TEXT
- `title` TEXT
- `relevant` INTEGER
- `body` TEXT
- `fetched_at` TEXT
- `doc_id` INTEGER

## pib_releases_fts
rows: ~2.3M · key columns: rowid

- `title`
- `body`
- `ministry`

## policy_docs
rows: ~3.1k · key columns: source_kind, source_id, section

- `source_kind` TEXT
- `source_id` TEXT
- `section` INTEGER
- `status` TEXT
- `is_policy` INTEGER
- `n_events` INTEGER
- `in_tok` INTEGER
- `out_tok` INTEGER
- `model` TEXT
- `done_at` TEXT
- `error` TEXT

## policy_eni_history
rows: ~5.5k · key columns: symbol, policy_name, asof_date

- `history_id` INTEGER
- `symbol` TEXT
- `policy_name` TEXT
- `asof_date` TEXT
- `net_impact_score` REAL
- `severity` REAL
- `source` TEXT
- `created_at` TEXT

## policy_events
rows: ~21.8k · key columns: id, source_kind, source_id

- `id` INTEGER
- `source_kind` TEXT
- `source_id` TEXT
- `section` INTEGER
- `published_at` TEXT
- `title` TEXT
- `policy_name` TEXT
- `instrument` TEXT
- `stage` TEXT
- `direction_for_industry` TEXT
- `sectors` TEXT
- `companies` TEXT
- `products` TEXT
- `amount_inr_crore` REAL
- `old_value` TEXT
- `new_value` TEXT
- `unit` TEXT
- `effective_date` TEXT
- `end_date` TEXT
- `geography` TEXT
- `quote` TEXT
- `quote_ok` INTEGER
- `model` TEXT
- `extracted_at` TEXT

## policy_events_fts
rows: ~21.8k · key columns: rowid

- `policy_name`
- `quote`

## portfolio_actions
rows: ~3.1k · key columns: action_id, symbol, action_date

- `action_id` INTEGER
- `symbol` TEXT
- `action` TEXT
- `action_date` TEXT
- `entry_price` REAL
- `target_price` REAL
- `stop_loss` REAL
- `thesis_ref` TEXT
- `status` TEXT
- `closed_date` TEXT
- `exit_price` REAL
- `pnl_pct` REAL

## price_bands
rows: ~1.1M · key columns: date, symbol, series

- `date` TEXT
- `symbol` TEXT
- `series` TEXT
- `band` TEXT
- `remarks` TEXT

## pruning_decay_config
rows: ~7 · key columns: category, half_life_months, lambda, significance_floor, prob_cutoff, is_structural_milestone

- `category` TEXT
- `half_life_months` REAL
- `lambda` REAL
- `significance_floor` REAL
- `prob_cutoff` REAL
- `is_structural_milestone` INTEGER

## quarterly_financials
rows: 15.2k · key columns: isin, symbol, quarter_end_date

- `id` INTEGER
- `isin` TEXT
- `symbol` TEXT
- `quarter_end_date` DATE
- `financial_year` TEXT
- `revenue_inr_cr` REAL
- `ebitda_inr_cr` REAL
- `ebitda_margin_pct` REAL
- `net_profit_inr_cr` REAL
- `pat_margin_pct` REAL
- `eps_inr` REAL
- `yoy_revenue_growth_pct` REAL
- `yoy_pat_growth_pct` REAL
- `qoq_revenue_growth_pct` REAL
- `qoq_pat_growth_pct` REAL
- `xbrl_file_path` TEXT
- `concall_pdf_path` TEXT
- `investor_presentation_path` TEXT
- `has_concall_transcript` BOOLEAN
- `created_at` TIMESTAMP
- `source` TEXT

## raw_documents
rows: 34.8k · key columns: doc_id

- `doc_id` INTEGER
- `title` TEXT
- `source_type` TEXT
- `published_date` TEXT
- `fiscal_period` TEXT
- `source_url` TEXT
- `creator_or_ministry` TEXT
- `created_at` TEXT
- `sha256_hash` TEXT
- `local_file_path` TEXT
- `file_size_bytes` INTEGER
- `is_structural_milestone` INTEGER
- `event_date` TEXT
- `event_source` TEXT
- `doc_version` INTEGER

## regulatory_political_risks
rows: ~7.9k · key columns: risk_id, symbol, policy_name

- `risk_id` INTEGER
- `company_id` INTEGER
- `ticker` TEXT
- `isin` TEXT
- `symbol` TEXT
- `policy_name` TEXT
- `risk_type` TEXT
- `factor_type` TEXT
- `severity_score` REAL
- `probability` REAL
- `net_impact_score` REAL
- `time_horizon` TEXT
- `created_at` TEXT
- `coverage_status` TEXT

## ripple_effects
rows: ~379 · key columns: ripple_id, event_id, parent_ripple_id

- `ripple_id` INTEGER
- `event_id` TEXT
- `parent_ripple_id` INTEGER
- `order_level` INTEGER
- `target_type` TEXT
- `target_sector_id` INTEGER
- `target_industry_id` INTEGER
- `target_company_id` INTEGER
- `transmission_channel` TEXT
- `transmission_elasticity` REAL
- `raw_magnitude` REAL
- `probability` REAL
- `lag_time_months` INTEGER
- `significance_rank` REAL
- `created_at` TEXT
- `revision_count` INTEGER
- `last_revised_at` TEXT

## ripple_history
rows: ~76 · key columns: edge_key, asof_date

- `history_id` INTEGER
- `edge_key` TEXT
- `symbol` TEXT
- `event_id` TEXT
- `source_node_id` TEXT
- `target_node_id` TEXT
- `asof_date` TEXT
- `significance` REAL
- `beta` REAL
- `revision_count` INTEGER
- `source` TEXT
- `created_at` TEXT

## schema_meta
rows: ~13 · key columns: key

- `key` TEXT
- `value` TEXT

## security_master
rows: ~8.4k · key columns: isin

- `isin` TEXT
- `issuer` TEXT
- `name` TEXT
- `nse_symbol` TEXT
- `bse_code` TEXT
- `bse_symbol` TEXT
- `bse_status` TEXT
- `segment` TEXT
- `nse_listing_date` TEXT
- `first_trade` TEXT
- `last_trade` TEXT
- `last_seen_nse` TEXT
- `last_seen_bse` TEXT
- `in_master_companies` INTEGER
- `source` TEXT

## shareholding
rows: 40 · key columns: symbol, isin, quarter_end, record_id

- `symbol` TEXT
- `isin` TEXT
- `quarter_end` TEXT
- `broadcast_at` TEXT
- `revised` TEXT
- `record_id` TEXT
- `file` TEXT
- `promoter_pct`
- `promoter_pledged_pct`
- `promoter_encumbered_pct`
- `fii_pct`
- `dii_pct`
- `mf_pct`
- `insurance_pct`
- `retail_pct`
- `fpi_limit_utilised_pct`

## shp_facts
rows: ~30.5k · key columns: file, context, concept

- `file` TEXT
- `context` TEXT
- `concept` TEXT
- `value` TEXT

## shp_index
rows: ~156.9k · key columns: record_id, isin, quarter_end

- `record_id` TEXT
- `idx` TEXT
- `symbol` TEXT
- `isin` TEXT
- `name` TEXT
- `quarter_end` TEXT
- `broadcast_at` TEXT
- `submission_date` TEXT
- `promoter_pct` REAL
- `public_pct` REAL
- `revised` TEXT
- `xbrl` TEXT
- `file` TEXT

## shp_parsed
rows: ~40 · key columns: file

- `file` TEXT
- `n_facts` INTEGER
- `status` TEXT
- `parsed_at` TEXT

## substrate_quarantine
rows: ~11.0k · key columns: rule_id, table_name, row_key

- `rule_id` TEXT
- `table_name` TEXT
- `row_key` TEXT
- `severity` TEXT
- `reason` TEXT
- `detected_at` TEXT

## symbol_isin_history
rows: ~9.4k · key columns: exchange, symbol, isin, first_date

- `exchange` TEXT
- `symbol` TEXT
- `isin` TEXT
- `first_date` TEXT
- `last_date` TEXT
- `n_days` INTEGER

## tax_rules
rows: ~20 · key columns: rule, effective_from

- `rule` TEXT
- `value` REAL
- `effective_from` TEXT
- `effective_to` TEXT
- `basis` TEXT
- `announced_at` TEXT
- `policy_event_ids` TEXT
- `source_title` TEXT
- `source_url` TEXT
- `source_file` TEXT
- `source_page` INTEGER
- `quote` TEXT
- `quote_verified` INTEGER
- `note` TEXT
- `built_at` TEXT

## telegram_post_tags
rows: ~420 · key columns: post_id, symbol

- `post_id` TEXT
- `symbol` TEXT
- `isin` TEXT
- `method` TEXT
- `position` INT

## telegram_posts
rows: ~1.7k · key columns: id, channel_id, message_id

- `id` TEXT
- `channel_id` TEXT
- `channel_title` TEXT
- `thread_topic_id` INTEGER
- `thread_topic_name` TEXT
- `message_id` INTEGER
- `raw_message_text` TEXT
- `has_media` BOOLEAN
- `media_file_path` TEXT
- `ocr_extracted_text` TEXT
- `detected_symbols_json` TEXT
- `post_timestamp` TIMESTAMP
- `created_at` TIMESTAMP
- `button_links_json` TEXT

## tg_company_mentions
rows: ~261 · key columns: post_id, isin

- `topic_id` INTEGER
- `post_id` TEXT
- `message_id` INTEGER
- `post_ts_utc` TEXT
- `symbol` TEXT
- `isin` TEXT
- `source` TEXT

## tg_order_schedule
rows: ~1.0k · key columns: order_id, fy, q

- `order_id` TEXT
- `isin` TEXT
- `fy` INTEGER
- `q` INTEGER
- `amount_cr` REAL

## tg_orders
rows: ~219 · key columns: order_id, isin, symbol

- `order_id` TEXT
- `post_id` TEXT
- `message_id` INTEGER
- `kind` TEXT
- `isin` TEXT
- `symbol` TEXT
- `company` TEXT
- `customer` TEXT
- `description` TEXT
- `value_cr` REAL
- `annual_cr` REAL
- `duration_months` REAL
- `duration_source` TEXT
- `revenue_cr` REAL
- `revenue_fy` TEXT
- `pct_of_revenue` REAL
- `mcap_cr` REAL
- `price_at_alert` REAL
- `known_at` TEXT
- `known_at_source` TEXT
- `post_ts_utc` TEXT
- `filing_url` TEXT

## tg_pead_signals
rows: ~731 · key columns: post_id, symbol

- `post_id` TEXT
- `message_id` INTEGER
- `post_ts_utc` TEXT
- `company_text` TEXT
- `label` TEXT
- `symbol` TEXT
- `isin` TEXT
- `symbol_source` TEXT
- `filing_url` TEXT
- `screener_url` TEXT
- `is_test_post` INTEGER

## v_document_pit
rows: 127.2k · key columns: id, isin, symbol, pit_date

- `id` INTEGER
- `isin` TEXT
- `symbol` TEXT
- `doc_type` TEXT
- `title` TEXT
- `source_url` TEXT
- `pit_ts`
- `pit_date`
- `pit_basis`
- `call_date` TEXT
- `fiscal_period_end` TEXT
- `crawl_doc_date` DATE

## visual_evidence_artifacts
rows: ~100 · key columns: artifact_id, doc_id, chunk_id

- `artifact_id` INTEGER
- `doc_id` INTEGER
- `chunk_id` INTEGER
- `timestamp_start_sec` INTEGER
- `timestamp_end_sec` INTEGER
- `artifact_type` TEXT
- `extracted_visual_data` TEXT
- `visual_description` TEXT
- `moat_implication` TEXT
- `frame_snapshot_url` TEXT
- `confidence_score` REAL
- `symbol` TEXT
- `source_url` TEXT
