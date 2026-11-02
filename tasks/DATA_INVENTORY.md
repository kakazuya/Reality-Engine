# Data inventory: generated, do not edit

Generated 2026-11-02 08:35 IST by `reality_engine/scripts/data_inventory.py`. Check here before saying data is not held. 'Undocumented' means no main doc names it.
Undocumented: 45 tables and 51 of 66 raw folders.

## Report tables held cell by cell (`equity_intelligence.mkt_report_cells`)

- `nsdl_fpi_fortnight`: 187 files, for example `FIIInvestSectorApril302020.html`, `FIIInvestSector_September302019.html`
- `nsdl_limits`: 2 files, for example `breach_list_2026-10-06.html`, `red_flag_list_2026-10-06.html`
- `nsdl_reports`: 7 files, for example `auc_category_2026-10-06.html`, `odi_pnotes_2026-10-06.html`
- `nse_fii_stats`: 1924 files, for example `fii_stats_01-Apr-2019.xls`, `fii_stats_31-Oct-2025.xls`

## Databases

| Database | Table | Rows (about) | Named in docs |
|---|---|---:|---|
| ar_facts.db | `ar_claims` | 140,322 | yes |
| ar_facts.db | `ar_docs` | 140,692 | yes |
| ar_facts.db | `ar_facts` | 32,981,115 | yes |
| ar_facts.db | `ar_facts_dropped` | 449,354 | yes |
| ar_facts.db | `ar_facts_replaced` | 31,533 | yes |
| ar_facts.db | `ar_pieces` | 681,871 | yes |
| ar_facts.db | `ar_skipped_pages` | 521,224 | yes |
| bse_announcements.db | `ann` | 1,947,087 | yes |
| bse_announcements.db | `done` | 33,194 | yes |
| chunks_v2.db | `deck_chunks` | 203,378 | **undocumented** |
| chunks_v2.db | `deck_docs` | 23,405 | **undocumented** |
| concall_facts.db | `cc_docs` | 140,700 | yes |
| concall_facts.db | `cc_item_checks` | 646,563 | yes |
| concall_facts.db | `cc_items` | 720,692 | yes |
| deck_figures.db | `bad_docs` | 9 | yes |
| deck_figures.db | `call_log` | 0 | yes |
| deck_figures.db | `chart_trends` | 1,687 | yes |
| deck_figures.db | `deck_sources` | 26,575 | yes |
| deck_figures.db | `doc_pages` | 41,070 | yes |
| deck_figures.db | `facts` | 15,115,935 | yes |
| deck_figures.db | `facts_unit_fix` | 6,404,122 | yes |
| deck_figures.db | `outputs` | 822,151 | yes |
| deck_figures.db | `pages` | 932,586 | yes |
| deck_figures.db | `second_queue` | 0 | yes |
| deck_figures.db | `spend` | 71,629 | yes |
| equity_intelligence.db | `amfi_months` | 98 | yes |
| equity_intelligence.db | `annual_financials` | 14,833 | yes |
| equity_intelligence.db | `annual_financials_placeholder_archive` | 82 | yes |
| equity_intelligence.db | `ar_doc_identity` | 139,989 | yes |
| equity_intelligence.db | `ar_doc_scan` | 140,691 | yes |
| equity_intelligence.db | `board_meetings` | 122,774 | yes |
| equity_intelligence.db | `bse_annual_reports` | 76,273 | yes |
| equity_intelligence.db | `bse_annual_reports_fetch` | 12,933 | yes |
| equity_intelligence.db | `bulk_block_deals` | 271,800 | yes |
| equity_intelligence.db | `business_model_profiles` | 6,397 | yes |
| equity_intelligence.db | `business_model_profiles_demo` | 2,652 | yes |
| equity_intelligence.db | `chunk_symbol_tags` | 194 | yes |
| equity_intelligence.db | `circuit_hits` | 282,228 | yes |
| equity_intelligence.db | `company_business_features` | 1,031 | yes |
| equity_intelligence.db | `company_business_graph` | 20,620 | yes |
| equity_intelligence.db | `company_business_runs` | 4 | yes |
| equity_intelligence.db | `company_distilled_parameters` | 17,667 | yes |
| equity_intelligence.db | `company_distilled_parameters_placeholder_archive` | 847 | yes |
| equity_intelligence.db | `company_entity_edges` | 73,513 | yes |
| equity_intelligence.db | `company_forensic_health` | 4,284 | yes |
| equity_intelligence.db | `company_forensic_health_placeholder_archive` | 219 | yes |
| equity_intelligence.db | `company_industry` | 2,067 | yes |
| equity_intelligence.db | `company_peer_features` | 4,996 | yes |
| equity_intelligence.db | `company_peer_graph` | 51,540 | yes |
| equity_intelligence.db | `company_peer_runs` | 10 | yes |
| equity_intelligence.db | `corporate_actions` | 27,655 | yes |
| equity_intelligence.db | `corporate_documents` | 140,775 | yes |
| equity_intelligence.db | `corporate_status_flags` | 0 | yes |
| equity_intelligence.db | `countries` | 4 | yes |
| equity_intelligence.db | `daily_price_delivery` | 3,867,817 | yes |
| equity_intelligence.db | `distillation_runs` | 6 | yes |
| equity_intelligence.db | `document_chunks` | 2,947,086 | yes |
| equity_intelligence.db | `dynamic_parameter_definitions` | 5 | yes |
| equity_intelligence.db | `entity_graph_runs` | 1 | yes |
| equity_intelligence.db | `eod_correction_log` | 57 | yes |
| equity_intelligence.db | `eod_scrip_calls` | 5,623 | yes |
| equity_intelligence.db | `etf_inav` | 6,800 | yes |
| equity_intelligence.db | `etf_master` | 432 | yes |
| equity_intelligence.db | `etf_premium_daily` | 268,992 | yes |
| equity_intelligence.db | `etf_px` | 315,259 | yes |
| equity_intelligence.db | `financial_metrics` | 2,585 | yes |
| equity_intelligence.db | `financially_free_breadth` | 0 | yes |
| equity_intelligence.db | `forecast_skill_history` | 161 | yes |
| equity_intelligence.db | `fund_nav` | 349,647 | yes |
| equity_intelligence.db | `geographic_exposure` | 3,568 | yes |
| equity_intelligence.db | `graph_causal_edges` | 15 | yes |
| equity_intelligence.db | `graph_nodes` | 19 | yes |
| equity_intelligence.db | `inbox_ingestion_manifest` | 343 | yes |
| equity_intelligence.db | `index_membership` | 300 | yes |
| equity_intelligence.db | `index_tri` | 19,330 | yes |
| equity_intelligence.db | `industries` | 12 | yes |
| equity_intelligence.db | `insider_trades` | 0 | yes |
| equity_intelligence.db | `insider_trades_v2` | 333,712 | yes |
| equity_intelligence.db | `isin_rekey_log` | 7,789 | yes |
| equity_intelligence.db | `lens_activation_log` | 1,082 | yes |
| equity_intelligence.db | `macro_event_sources` | 59 | yes |
| equity_intelligence.db | `macro_events` | 30 | yes |
| equity_intelligence.db | `master_companies` | 6,940 | yes |
| equity_intelligence.db | `mkt_bse_deals` | 271,591 | yes |
| equity_intelligence.db | `mkt_bse_delivery_daily` | 7,542,297 | yes |
| equity_intelligence.db | `mkt_bse_eq_daily` | 7,542,386 | yes |
| equity_intelligence.db | `mkt_bse_index_daily` | 144,591 | yes |
| equity_intelligence.db | `mkt_bse_insider` | 153,904 | yes |
| equity_intelligence.db | `mkt_commodity_daily` | 25,255 | yes |
| equity_intelligence.db | `mkt_commodity_monthly` | 9,208 | yes |
| equity_intelligence.db | `mkt_fii_dii_cash` | 1,942 | yes |
| equity_intelligence.db | `mkt_load_log` | 25,591 | yes |
| equity_intelligence.db | `mkt_nsdl_fpi_daily` | 33,549 | yes |
| equity_intelligence.db | `mkt_nse_deals` | 278,888 | yes |
| equity_intelligence.db | `mkt_nse_eq_daily` | 1,388,730 | yes |
| equity_intelligence.db | `mkt_nse_full_daily` | 4,525,146 | yes |
| equity_intelligence.db | `mkt_nse_index_daily` | 207,044 | yes |
| equity_intelligence.db | `mkt_nse_insider` | 176,865 | yes |
| equity_intelligence.db | `mkt_nse_participant` | 19,285 | yes |
| equity_intelligence.db | `mkt_nse_pit_filings` | 3,924 | yes |
| equity_intelligence.db | `mkt_nse_pit_xbrl_facts` | 160,145 | yes |
| equity_intelligence.db | `mkt_nse_sast` | 37,121 | yes |
| equity_intelligence.db | `mkt_nse_short` | 46,011 | yes |
| equity_intelligence.db | `mkt_nse_sme_daily` | 254,181 | yes |
| equity_intelligence.db | `mkt_report_cells` | 532,344 | yes |
| equity_intelligence.db | `moat_evaluations` | 6,397 | yes |
| equity_intelligence.db | `moat_history` | 71,632 | yes |
| equity_intelligence.db | `model_explainer_rankings` | 94,968 | yes |
| equity_intelligence.db | `model_lens_weight_proposals` | 28 | yes |
| equity_intelligence.db | `model_validation_scores` | 51,392 | yes |
| equity_intelligence.db | `move_attribution` | 167,929 | yes |
| equity_intelligence.db | `news_visual_artifacts` | 52 | yes |
| equity_intelligence.db | `noise_floors` | 201 | yes |
| equity_intelligence.db | `nse_index_breadth` | 5,717 | yes |
| equity_intelligence.db | `nse_pr_days` | 783 | yes |
| equity_intelligence.db | `pc_restore_doc_links` | 63,761 | yes |
| equity_intelligence.db | `pib_days` | 1,844 | yes |
| equity_intelligence.db | `pib_ml_days` | 1,220 | yes |
| equity_intelligence.db | `pib_ml_langs` | 62 | yes |
| equity_intelligence.db | `pib_ml_match` | 14,416 | yes |
| equity_intelligence.db | `pib_ml_releases` | 2,325,056 | yes |
| equity_intelligence.db | `pib_releases` | 2,327,861 | yes |
| equity_intelligence.db | `policy_docs` | 3,064 | yes |
| equity_intelligence.db | `policy_eni_history` | 5,470 | yes |
| equity_intelligence.db | `policy_events` | 21,793 | yes |
| equity_intelligence.db | `portfolio_actions` | 3,084 | yes |
| equity_intelligence.db | `price_bands` | 1,054,356 | yes |
| equity_intelligence.db | `pruning_decay_config` | 7 | yes |
| equity_intelligence.db | `quarterly_financials` | 18,307 | yes |
| equity_intelligence.db | `quarterly_financials_placeholder_archive` | 93 | yes |
| equity_intelligence.db | `raw_documents` | 39,674 | yes |
| equity_intelligence.db | `regulatory_political_risks` | 7,909 | yes |
| equity_intelligence.db | `ripple_effects` | 379 | yes |
| equity_intelligence.db | `ripple_history` | 76 | yes |
| equity_intelligence.db | `schema_meta` | 15 | yes |
| equity_intelligence.db | `security_master` | 8,434 | yes |
| equity_intelligence.db | `seed_countries_demo` | 3 | yes |
| equity_intelligence.db | `seed_industries_demo` | 12 | yes |
| equity_intelligence.db | `shp_facts` | 30,509 | yes |
| equity_intelligence.db | `shp_index` | 156,927 | yes |
| equity_intelligence.db | `shp_parsed` | 40 | yes |
| equity_intelligence.db | `substrate_quarantine` | 11,048 | yes |
| equity_intelligence.db | `symbol_isin_history` | 9,360 | yes |
| equity_intelligence.db | `tax_rules` | 20 | yes |
| equity_intelligence.db | `telegram_post_tags` | 420 | yes |
| equity_intelligence.db | `telegram_posts` | 4,527 | yes |
| equity_intelligence.db | `tg_company_mentions` | 261 | yes |
| equity_intelligence.db | `tg_order_schedule` | 1,040 | yes |
| equity_intelligence.db | `tg_orders` | 219 | yes |
| equity_intelligence.db | `tg_pead_signals` | 731 | yes |
| equity_intelligence.db | `visual_evidence_artifacts` | 100 | yes |
| extract_proto3.db | `balance_sheet_lines` | 173 | **undocumented** |
| extract_proto3.db | `capex_project` | 4 | yes |
| extract_proto3.db | `cash_flow_lines` | 91 | **undocumented** |
| extract_proto3.db | `company_capacity_utilisation` | 156 | yes |
| extract_proto3.db | `company_cost_structure` | 3 | yes |
| extract_proto3.db | `company_debt_mix` | 6 | yes |
| extract_proto3.db | `company_operating_metrics` | 378 | yes |
| extract_proto3.db | `company_price_revision` | 6 | yes |
| extract_proto3.db | `company_segment_pnl` | 72 | yes |
| extract_proto3.db | `extract_arm` | 29 | **undocumented** |
| extract_proto3.db | `extract_call` | 443 | **undocumented** |
| extract_proto3.db | `extract_done` | 11 | **undocumented** |
| extract_proto3.db | `extract_handcheck` | 0 | **undocumented** |
| extract_proto3.db | `extract_recall` | 0 | **undocumented** |
| extract_proto3.db | `extract_reject` | 634 | **undocumented** |
| extract_proto3.db | `extract_run` | 2 | **undocumented** |
| extract_proto3.db | `extract_selection` | 872 | **undocumented** |
| extract_proto3.db | `lender_metrics` | 60 | **undocumented** |
| extract_proto3.db | `order_book_contract` | 4 | yes |
| extract_proto3.db | `order_intake` | 12 | yes |
| extract_proto3.db | `rating_action` | 16 | yes |
| extract_proto3.db | `supply_link` | 0 | yes |
| extract_proto3.db | `tax_reconciliation` | 200 | **undocumented** |
| extract_proto3.db | `unit_volume` | 19 | **undocumented** |
| pilot/macro_all.db | `macro_claim` | 21,793 | yes |
| pilot/macro_all.db | `macro_claim_target` | 44,742 | yes |
| pilot/macro_all.db | `macro_doc` | 456 | yes |
| pilot/pilot60/chunks_v3_history.db | `build_run` | 5 | yes |
| pilot/pilot60/chunks_v3_history.db | `chunk` | 212,276 | yes |
| pilot/pilot60/chunks_v3_history.db | `chunk_entity` | 0 | yes |
| pilot/pilot60/chunks_v3_history.db | `chunk_tag` | 527,851 | yes |
| pilot/pilot60/chunks_v3_history.db | `chunk_vec_ref` | 0 | yes |
| pilot/pilot60/chunks_v3_history.db | `coverage_scorecard` | 0 | yes |
| pilot/pilot60/chunks_v3_history.db | `doc` | 18,031 | yes |
| pilot/pilot60/chunks_v3_history.db | `history_outcome` | 31,509 | **undocumented** |
| pilot/pilot60/chunks_v3_history.db | `result_note` | 0 | yes |
| pilot/pilot60/chunks_v3_history.db | `tag_vocab` | 64 | yes |
| pilot/pilot60/chunks_v3_pilot.db | `build_run` | 5 | yes |
| pilot/pilot60/chunks_v3_pilot.db | `chunk` | 108,404 | yes |
| pilot/pilot60/chunks_v3_pilot.db | `chunk_entity` | 304,625 | yes |
| pilot/pilot60/chunks_v3_pilot.db | `chunk_tag` | 321,794 | yes |
| pilot/pilot60/chunks_v3_pilot.db | `chunk_vec_ref` | 0 | yes |
| pilot/pilot60/chunks_v3_pilot.db | `coverage_scorecard` | 0 | yes |
| pilot/pilot60/chunks_v3_pilot.db | `doc` | 2,498 | yes |
| pilot/pilot60/chunks_v3_pilot.db | `result_note` | 0 | yes |
| pilot/pilot60/chunks_v3_pilot.db | `tag_vocab` | 32 | yes |
| pilot/pilot60/chunks_v3_pilot_capped.db | `build_run` | 2 | yes |
| pilot/pilot60/chunks_v3_pilot_capped.db | `chunk` | 36,494 | yes |
| pilot/pilot60/chunks_v3_pilot_capped.db | `chunk_entity` | 107,121 | yes |
| pilot/pilot60/chunks_v3_pilot_capped.db | `chunk_tag` | 104,765 | yes |
| pilot/pilot60/chunks_v3_pilot_capped.db | `chunk_vec_ref` | 0 | yes |
| pilot/pilot60/chunks_v3_pilot_capped.db | `coverage_scorecard` | 0 | yes |
| pilot/pilot60/chunks_v3_pilot_capped.db | `doc` | 433 | yes |
| pilot/pilot60/chunks_v3_pilot_capped.db | `result_note` | 0 | yes |
| pilot/pilot60/chunks_v3_pilot_capped.db | `tag_vocab` | 32 | yes |
| pilot/pilot60/extract_pilot60.db | `capex_project` | 19 | yes |
| pilot/pilot60/extract_pilot60.db | `company_capacity_utilisation` | 70 | yes |
| pilot/pilot60/extract_pilot60.db | `company_cost_structure` | 21 | yes |
| pilot/pilot60/extract_pilot60.db | `company_debt_mix` | 18 | yes |
| pilot/pilot60/extract_pilot60.db | `company_operating_metrics` | 55 | yes |
| pilot/pilot60/extract_pilot60.db | `company_price_revision` | 61 | yes |
| pilot/pilot60/extract_pilot60.db | `company_segment_pnl` | 51 | yes |
| pilot/pilot60/extract_pilot60.db | `extract_done` | 11 | **undocumented** |
| pilot/pilot60/extract_pilot60.db | `extract_handcheck` | 150 | **undocumented** |
| pilot/pilot60/extract_pilot60.db | `extract_recall` | 20 | **undocumented** |
| pilot/pilot60/extract_pilot60.db | `extract_reject` | 318 | **undocumented** |
| pilot/pilot60/extract_pilot60.db | `extract_run` | 6 | **undocumented** |
| pilot/pilot60/extract_pilot60.db | `extract_selection` | 5,208 | **undocumented** |
| pilot/pilot60/extract_pilot60.db | `order_book_contract` | 31 | yes |
| pilot/pilot60/extract_pilot60.db | `order_intake` | 21 | yes |
| pilot/pilot60/extract_pilot60.db | `rating_action` | 230 | yes |
| pilot/pilot60/extract_pilot60.db | `supply_link` | 0 | yes |
| pilot/pilot60/facts_pilot.db | `build_run` | 1 | yes |
| pilot/pilot60/facts_pilot.db | `company_interest_cover` | 12,762 | yes |
| pilot/pilot60/facts_pilot.db | `company_metric_series` | 1,056,589 | yes |
| pilot/pilot60/facts_pilot.db | `company_result_pit` | 60,023 | yes |
| pilot/pilot60/facts_pilot.db | `company_segment_pnl` | 34,451 | yes |
| pilot/pilot60/facts_pilot.db | `company_working_capital` | 9,144 | yes |
| pilot/pilot60/facts_pilot.db | `xbrl_concept_map` | 110 | yes |
| pilot/pilot60/market_state_b.db | `build_run` | 1 | yes |
| pilot/pilot60/market_state_b.db | `company_membership_pit` | 10,895 | yes |
| pilot/pilot60/market_state_b.db | `fno_oi_daily` | 16,242,454 | yes |
| pilot/pilot60/market_state_b.db | `index_list` | 133 | yes |
| pilot/pilot60/market_state_b.db | `mkt_nse_full_daily` | 4,290,443 | yes |
| pilot/pilot60/market_state_b.db | `series_meta` | 22 | yes |
| pilot/pilot60/market_state_b.db | `series_observation` | 7,062 | yes |
| pilot/pilot60/market_state_pilot.db | `build_run` | 0 | yes |
| pilot/pilot60/market_state_pilot.db | `company_membership_pit` | 10,895 | yes |
| pilot/pilot60/market_state_pilot.db | `company_ownership_pit` | 49,126 | yes |
| pilot/pilot60/market_state_pilot.db | `company_sector_pit` | 0 | yes |
| pilot/pilot60/market_state_pilot.db | `company_state_daily` | 7,258,000 | yes |
| pilot/pilot60/market_state_pilot.db | `event_day0` | 3,010,610 | yes |
| pilot/pilot60/market_state_pilot.db | `event_leakage_window` | 0 | yes |
| pilot/pilot60/market_state_pilot.db | `index_list` | 133 | yes |
| pilot/pilot60/market_state_pilot.db | `isin_rekey_map` | 0 | yes |
| pilot/pilot60/market_state_pilot.db | `theme_map` | 0 | yes |
| pilot/pilot60/results_notes_chunks.db | `build_run` | 1 | yes |
| pilot/pilot60/results_notes_chunks.db | `chunk` | 1,131 | yes |
| pilot/pilot60/results_notes_chunks.db | `chunk_entity` | 3,368 | yes |
| pilot/pilot60/results_notes_chunks.db | `chunk_tag` | 2,466 | yes |
| pilot/pilot60/results_notes_chunks.db | `chunk_vec_ref` | 0 | yes |
| pilot/pilot60/results_notes_chunks.db | `coverage_scorecard` | 0 | yes |
| pilot/pilot60/results_notes_chunks.db | `doc` | 76 | yes |
| pilot/pilot60/results_notes_chunks.db | `result_note` | 0 | yes |
| pilot/pilot60/results_notes_chunks.db | `tag_vocab` | 32 | yes |
| pilot/pilot60/sector_pit.db | `company_sector_pit` | 482 | yes |
| pilot/pilot60_history_manifest.db | `docs` | 244,942 | yes |
| pilot/results_notes.db | `results_notes` | 17,989 | yes |
| pilot/v4/fact_v4_pilot.db | `atom_status` | 43 | **undocumented** |
| pilot/v4/fact_v4_pilot.db | `fact` | 1,563,625 | yes |
| pilot/v4/fact_v4_pilot.db | `membership` | 10,895 | yes |
| pilot/v4/fact_v4_pilot.db | `pilot_universe` | 60 | **undocumented** |
| pilot/v4/fact_v4_pilot_oi.db | `fact` | 6,927,092 | yes |
| pilot/v4/fact_v4_pilot_oi.db | `pilot_universe` | 60 | **undocumented** |
| pilot/v4/quarters_pilot60.db | `company_quarter_series` | 20,610 | **undocumented** |
| pilot/v4/quarters_pilot60.db | `pilot_quarter_mix` | 3 | **undocumented** |
| pilot/v4/quarters_pilot60.db | `quarter_derivation_counts` | 6 | **undocumented** |
| pilot/v4/quarters_pilot60.db | `quarter_handcheck` | 14,226 | **undocumented** |
| pilot/v4/quarters_pilot60.db | `quarter_sample` | 30 | **undocumented** |
| pilot/v4/shp_xbrl_pilot.db | `fact` | 5,154 | yes |
| pilot/v4/shp_xbrl_pilot.db | `filings` | 566 | yes |
| pilot/v4/shp_xbrl_pilot.db | `xcheck` | 1,126 | **undocumented** |
| pilot/v4/v4.db | `attention` | 0 | **undocumented** |
| pilot/v4/v4.db | `claim` | 647,516 | yes |
| pilot/v4/v4.db | `edge` | 0 | yes |
| pilot/v4/v4.db | `hypothesis` | 0 | **undocumented** |
| pilot/v4/v4.db | `own_estimate` | 2,325 | **undocumented** |
| pilot/v4/v4.db | `own_estimate_band` | 12 | **undocumented** |
| pilot/v4/v4.db | `own_estimate_band_prev` | 12 | **undocumented** |
| pilot/v4/v4.db | `reaction_lag` | 0 | **undocumented** |
| pilot/v4/v4_vocab.db | `beam_answer` | 40,094 | **undocumented** |
| pilot/v4/v4_vocab.db | `beam_batch` | 10,009 | **undocumented** |
| pilot/v4/v4_vocab.db | `beam_context` | 148,634 | **undocumented** |
| pilot/v4/v4_vocab.db | `beam_run` | 3 | **undocumented** |
| pilot/v4/v4_vocab.db | `label` | 139 | yes |
| pilot/v4/v4_vocab.db | `map` | 148,652 | yes |
| pilot/v4/v4_vocab.db | `other_cluster` | 26,261 | **undocumented** |
| pilot/v4/v4_vocab.db | `surface` | 148,652 | **undocumented** |
| pilot/v4/v4_vocab_pass1_backup.db | `label` | 139 | yes |
| pilot/v4/v4_vocab_pass1_backup.db | `map` | 148,652 | yes |
| pilot/v4/v4_vocab_pass1_backup.db | `other_cluster` | 26,261 | **undocumented** |
| pilot/v4/v4_vocab_pass1_backup.db | `surface` | 148,652 | **undocumented** |
| results_notes.db | `docs` | 41,606 | yes |
| results_notes.db | `gate` | 21 | yes |
| results_notes.db | `notes` | 306,389 | yes |
| results_xbrl.db | `facts` | 13,941,210 | yes |
| results_xbrl.db | `filings` | 146,564 | yes |
| results_xbrl.db | `filings_isin` | 183,029 | yes |

## Raw folders on D

| Folder | Files | GB | Newest file | Named in docs |
|---|---:|---:|---|---|
| _dedupe | 1 | 0.00 | 2026-10-28 `sha_index.db` | **undocumented** |
| _migration | 1 | 0.00 | 2026-10-25 `2026-10-25.json` | **undocumented** |
| annual_report | 4,655 | 38.91 | 2026-10-28 `1712bec0-eb1b-4c0e-93cf-ffe2228ee187.pdf` | yes |
| ar_queue | 340 | 0.01 | 2026-10-24 `SCORE.md` | **undocumented** |
| bhavcopy | 34 | 0.01 | 2026-11-01 `sec_bhavdata_full_26102026.csv` | yes |
| bse_scrip_master | 1 | 0.00 | 2026-10-28 `scrip_master_equity_20261028.json` | **undocumented** |
| commodity_series | 325 | 0.03 | 2026-10-29 `_manifest.csv` | **undocumented** |
| concall_pdfs | 11,101 | 11.62 | 2026-10-28 `_manifest.jsonl` | **undocumented** |
| concall_pdfs_probe | 773 | 0.75 | 2026-10-27 `6aa7205671446542e32f86921793b514dd4d8d37de8b1809b3` | **undocumented** |
| concall_refetch | 2 | 0.00 | 2026-10-28 `dedupe_pilot_pairs200.json` | **undocumented** |
| deck | 1,404 | 4.09 | 2026-10-28 `e1e98fb9-f8e2-4287-b236-52025c4c4dff.pdf` | yes |
| deck_page_text | 48 | 0.05 | 2026-10-26 `pilot_map.jsonl` | **undocumented** |
| deck_real_pilot | 49 | 0.22 | 2026-10-26 `manifest.json` | **undocumented** |
| deck_real_test300 | 289 | 1.27 | 2026-10-26 `manifest.json` | **undocumented** |
| decks | 184 | 0.95 | 2026-10-28 `20260425_40069350-77ce-40d5-8148-9556a268f1dc.pdf` | yes |
| decks_full | 23,324 | 116.02 | 2026-10-26 `_tree3.log` | **undocumented** |
| fo_bhavcopy | 3,861 | 9.63 | 2026-10-29 `2026-10-28.csv` | **undocumented** |
| index_constituents | 3 | 0.00 | 2026-10-20 `niftymidcap150_current.csv` | **undocumented** |
| index_history | 454 | 0.12 | 2026-10-28 `current_niftysmallcap250.csv` | **undocumented** |
| input_cost_series | 22 | 0.00 | 2026-10-29 `wpi_items.csv` | **undocumented** |
| kec_transcripts | 45 | 0.01 | 2026-11-02 `_known_at.json` | **undocumented** |
| macro_pdfs | 0 | 0.00 | - | **undocumented** |
| material_announcement | 6,621 | 16.73 | 2026-10-28 `105432.pdf` | **undocumented** |
| nse_announcements | 19,593 | 33.12 | 2026-10-28 `_manifest.csv` | **undocumented** |
| nse_shp_xbrl_pilot | 563 | 0.01 | 2026-10-31 `SHP_199080_1470050_24062025105707_WEB.xml.gz` | **undocumented** |
| originals_lists | 20 | 0.01 | 2026-10-28 `todo_ann_part2.manifest.csv` | **undocumented** |
| pilot60_history | 21,250 | 36.41 | 2026-11-01 `manifest.csv` | **undocumented** |
| price_bands | 1,685 | 0.19 | 2026-10-28 `_manifest.jsonl` | yes |
| raw_market/amfi_nav | 3 | 0.00 | 2026-10-25 `2026-10.txt.gz` | **undocumented** |
| raw_market/bse_bhav | 17 | 0.01 | 2026-10-26 `_manifest.csv` | **undocumented** |
| raw_market/bse_block | 95 | 0.00 | 2026-10-26 `_manifest.csv` | **undocumented** |
| raw_market/bse_bulk | 96 | 0.03 | 2026-10-26 `_manifest.csv` | **undocumented** |
| raw_market/bse_corpact | 2 | 0.00 | 2026-10-24 `2026-10-14_2026-10-24.json` | **undocumented** |
| raw_market/bse_deliv | 17 | 0.00 | 2026-10-26 `_manifest.csv` | yes |
| raw_market/bse_index | 136 | 0.00 | 2026-10-24 `T10BNK_2026.json` | yes |
| raw_market/bse_insider | 2 | 0.00 | 2026-10-24 `_manifest.csv` | yes |
| raw_market/mc_fiidii | 2 | 0.00 | 2026-10-24 `2026.csv` | **undocumented** |
| raw_market/nsdl_fpi_daily | 2 | 0.00 | 2026-10-24 `_manifest.csv` | yes |
| raw_market/nsdl_fpi_fortnight | 2 | 0.00 | 2026-11-01 `FIIInvestSector_Oct152026.html` | **undocumented** |
| raw_market/nse_block | 12 | 0.00 | 2026-10-26 `_manifest.csv` | **undocumented** |
| raw_market/nse_bulk | 16 | 0.01 | 2026-10-26 `_manifest.csv` | **undocumented** |
| raw_market/nse_cm_isin | 8 | 0.00 | 2026-10-24 `_manifest.csv` | **undocumented** |
| raw_market/nse_corpact | 2 | 0.00 | 2026-10-24 `_manifest.csv` | **undocumented** |
| raw_market/nse_corpact_sme | 2 | 0.00 | 2026-10-24 `_manifest.csv` | **undocumented** |
| raw_market/nse_fii_stats | 8 | 0.00 | 2026-10-24 `_manifest.csv` | **undocumented** |
| raw_market/nse_full | 14 | 0.00 | 2026-10-26 `sec_bhavdata_full_01022026.csv` | yes |
| raw_market/nse_index | 8 | 0.00 | 2026-10-24 `ind_close_all_23102026.csv` | yes |
| raw_market/nse_integrated_equities | 1 | 0.00 | 2026-10-25 `page_001.json` | **undocumented** |
| raw_market/nse_integrated_sme | 10 | 0.00 | 2026-10-25 `page_010.json` | **undocumented** |
| raw_market/nse_part_oi | 8 | 0.00 | 2026-10-24 `_manifest.csv` | **undocumented** |
| raw_market/nse_part_vol | 8 | 0.00 | 2026-10-24 `fao_participant_vol_23102026.csv` | **undocumented** |
| raw_market/nse_pit_gg | 2 | 0.00 | 2026-10-24 `_manifest.csv` | **undocumented** |
| raw_market/nse_pit_gg_sme | 2 | 0.00 | 2026-10-24 `_manifest.csv` | **undocumented** |
| raw_market/nse_pit_gg_xml | 62 | 0.00 | 2026-10-24 `IT_24515_WebXMLFile_20261014_123855940.xml` | **undocumented** |
| raw_market/nse_results_xbrl | 5,402 | 0.46 | 2026-10-25 `INTEGRATED_FILING_NONINDAS_1745457_24102026073743_` | **undocumented** |
| raw_market/nse_sast | 2 | 0.00 | 2026-10-24 `2026-10-14_2026-10-24.json` | yes |
| raw_market/nse_short | 7 | 0.00 | 2026-10-24 `_manifest.csv` | yes |
| rbi | 106 | 0.06 | 2026-10-17 `12833.pdf` | yes |
| reddit | 42 | 0.48 | 2026-10-28 `IndiaTax.jsonl` | yes |
| results_notes_refetch | 3 | 0.02 | 2026-11-02 `483823e363b701d28b8d5d3d567695482ec330abdd454c7802` | **undocumented** |
| results_pdfs | 158 | 0.97 | 2026-10-27 `2e96bdf76e8573130525883d589bea959fabc389710ad7fd99` | **undocumented** |
| runners | 20 | 0.00 | 2026-10-29 `RESUME_2026-10-29.md` | **undocumented** |
| tax_sources | 5 | 0.01 | 2026-10-20 `nse_circular_FATAX56235_stt_2023.pdf` | **undocumented** |
| user_research | 803 | 32.77 | 2026-11-02 `LISTENING_CHECK.md` | **undocumented** |
| user_research_drive | 236 | 0.60 | 2026-10-26 `_native_blocked.txt` | **undocumented** |
| vahan | 8 | 0.00 | 2026-11-01 `monthly_2w_ev_by_maker.csv` | **undocumented** |
