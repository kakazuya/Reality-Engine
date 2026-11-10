# Data inventory: generated, do not edit

Generated 2026-11-10 05:00 IST by `reality_engine/scripts/data_inventory.py`. Check here before saying data is not held. 'Undocumented' means no main doc names it.
Undocumented: 0 tables and 2 of 73 raw folders.

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
| equity_intelligence.db | `bulk_block_deals` | 272,805 | yes |
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
| equity_intelligence.db | `corporate_actions` | 27,722 | yes |
| equity_intelligence.db | `corporate_documents` | 140,775 | yes |
| equity_intelligence.db | `corporate_status_flags` | 0 | yes |
| equity_intelligence.db | `countries` | 4 | yes |
| equity_intelligence.db | `daily_price_delivery` | 8,800,128 | yes |
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
| equity_intelligence.db | `mkt_bse_deals` | 272,211 | yes |
| equity_intelligence.db | `mkt_bse_delivery_daily` | 7,593,049 | yes |
| equity_intelligence.db | `mkt_bse_eq_daily` | 7,598,245 | yes |
| equity_intelligence.db | `mkt_bse_index_daily` | 146,095 | yes |
| equity_intelligence.db | `mkt_bse_insider` | 153,904 | yes |
| equity_intelligence.db | `mkt_commodity_daily` | 25,255 | yes |
| equity_intelligence.db | `mkt_commodity_monthly` | 9,208 | yes |
| equity_intelligence.db | `mkt_fii_dii_cash` | 1,942 | yes |
| equity_intelligence.db | `mkt_load_log` | 25,791 | yes |
| equity_intelligence.db | `mkt_nsdl_fpi_daily` | 33,549 | yes |
| equity_intelligence.db | `mkt_nse_deals` | 279,513 | yes |
| equity_intelligence.db | `mkt_nse_eq_daily` | 1,388,730 | yes |
| equity_intelligence.db | `mkt_nse_full_daily` | 4,564,083 | yes |
| equity_intelligence.db | `mkt_nse_index_daily` | 208,865 | yes |
| equity_intelligence.db | `mkt_nse_insider` | 176,865 | yes |
| equity_intelligence.db | `mkt_nse_participant` | 19,285 | yes |
| equity_intelligence.db | `mkt_nse_pit_filings` | 4,032 | yes |
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
| equity_intelligence.db | `shp_index` | 160,111 | yes |
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
| extract_proto3.db | `balance_sheet_lines` | 173 | yes |
| extract_proto3.db | `capex_project` | 4 | yes |
| extract_proto3.db | `cash_flow_lines` | 91 | yes |
| extract_proto3.db | `company_capacity_utilisation` | 156 | yes |
| extract_proto3.db | `company_cost_structure` | 3 | yes |
| extract_proto3.db | `company_debt_mix` | 6 | yes |
| extract_proto3.db | `company_operating_metrics` | 378 | yes |
| extract_proto3.db | `company_price_revision` | 6 | yes |
| extract_proto3.db | `company_segment_pnl` | 72 | yes |
| extract_proto3.db | `extract_arm` | 29 | yes |
| extract_proto3.db | `extract_call` | 443 | yes |
| extract_proto3.db | `extract_done` | 11 | yes |
| extract_proto3.db | `extract_handcheck` | 0 | yes |
| extract_proto3.db | `extract_recall` | 0 | yes |
| extract_proto3.db | `extract_reject` | 634 | yes |
| extract_proto3.db | `extract_run` | 2 | yes |
| extract_proto3.db | `extract_selection` | 872 | yes |
| extract_proto3.db | `lender_metrics` | 60 | yes |
| extract_proto3.db | `order_book_contract` | 4 | yes |
| extract_proto3.db | `order_intake` | 12 | yes |
| extract_proto3.db | `rating_action` | 16 | yes |
| extract_proto3.db | `supply_link` | 0 | yes |
| extract_proto3.db | `tax_reconciliation` | 200 | yes |
| extract_proto3.db | `unit_volume` | 19 | yes |
| pilot/macro_all.db | `macro_claim` | 21,793 | yes |
| pilot/macro_all.db | `macro_claim_target` | 44,742 | yes |
| pilot/macro_all.db | `macro_doc` | 456 | yes |
| pilot/pilot60_history_manifest.db | `docs` | 303,790 | yes |
| pilot/results_notes.db | `results_notes` | 17,989 | yes |
| results_notes.db | `docs` | 41,606 | yes |
| results_notes.db | `gate` | 21 | yes |
| results_notes.db | `notes` | 306,389 | yes |
| results_xbrl.db | `facts` | 14,018,478 | yes |
| results_xbrl.db | `filings` | 146,934 | yes |
| results_xbrl.db | `filings_isin` | 183,029 | yes |
| pilot3/pages.db | `doc` | 15,348 | yes |
| pilot3/pages.db | `doc_page` | 23,259 | yes |

## Raw folders on D

| Folder | Files | GB | Newest file | Named in docs |
|---|---:|---:|---|---|
| _dedupe | 1 | 0.00 | 2026-10-28 `sha_index.db` | yes |
| _migration | 0 | 0.00 | - | yes |
| annual_report | 0 | 0.00 | - | yes |
| ar_queue | 0 | 0.00 | - | yes |
| bhavcopy | 0 | 0.00 | - | yes |
| bse_scrip_master | 0 | 0.00 | - | yes |
| commodity_series | 0 | 0.00 | - | yes |
| concall_pdfs | 0 | 0.00 | - | yes |
| concall_pdfs_probe | 0 | 0.00 | - | yes |
| concall_refetch | 0 | 0.00 | - | yes |
| deck | 0 | 0.00 | - | yes |
| deck_page_text | 0 | 0.00 | - | yes |
| deck_real_pilot | 0 | 0.00 | - | yes |
| deck_real_test300 | 0 | 0.00 | - | yes |
| decks | 0 | 0.00 | - | yes |
| decks_full | 0 | 0.00 | - | yes |
| ETERNAL_site_documents | 0 | 0.00 | - | **undocumented** |
| fo_bhavcopy | 0 | 0.00 | - | yes |
| HDFCBANK_site_documents | 0 | 0.00 | - | **undocumented** |
| index_constituents | 0 | 0.00 | - | yes |
| index_history | 0 | 0.00 | - | yes |
| INFY_site_documents | 0 | 0.00 | - | yes |
| input_cost_series | 0 | 0.00 | - | yes |
| kec_transcripts | 0 | 0.00 | - | yes |
| macro_pdfs | 0 | 0.00 | - | yes |
| maruti_transcripts | 0 | 0.00 | - | yes |
| material_announcement | 0 | 0.00 | - | yes |
| nse_announcements | 0 | 0.00 | - | yes |
| nse_shp_xbrl_pilot | 777 | 0.01 | 2026-11-09 `SHP_1733654_07102026112959_WEB.xml.gz` | yes |
| originals_lists | 0 | 0.00 | - | yes |
| pilot60_history | 15,056 | 23.46 | 2026-11-10 `manifest.csv` | yes |
| price_bands | 0 | 0.00 | - | yes |
| raw_market/amfi_nav | 0 | 0.00 | - | yes |
| raw_market/bse_bhav | 5 | 0.00 | 2026-11-09 `BhavCopy_BSE_CM_0_0_0_20261109_F_0000.CSV` | yes |
| raw_market/bse_block | 0 | 0.00 | - | yes |
| raw_market/bse_bulk | 0 | 0.00 | - | yes |
| raw_market/bse_corpact | 0 | 0.00 | - | yes |
| raw_market/bse_deliv | 4 | 0.00 | 2026-11-09 `_manifest.csv` | yes |
| raw_market/bse_index | 0 | 0.00 | - | yes |
| raw_market/bse_insider | 0 | 0.00 | - | yes |
| raw_market/masters | 11 | 0.06 | 2026-10-08 `nse_SME_EQUITY_L.csv` | yes |
| raw_market/mc_fiidii | 0 | 0.00 | - | yes |
| raw_market/nsdl_fpi_daily | 0 | 0.00 | - | yes |
| raw_market/nsdl_fpi_fortnight | 0 | 0.00 | - | yes |
| raw_market/nse_block | 0 | 0.00 | - | yes |
| raw_market/nse_bulk | 0 | 0.00 | - | yes |
| raw_market/nse_cm_isin | 0 | 0.00 | - | yes |
| raw_market/nse_corpact | 0 | 0.00 | - | yes |
| raw_market/nse_corpact_sme | 0 | 0.00 | - | yes |
| raw_market/nse_fii_stats | 0 | 0.00 | - | yes |
| raw_market/nse_full | 5 | 0.00 | 2026-11-09 `sec_bhavdata_full_09112026.csv` | yes |
| raw_market/nse_index | 5 | 0.00 | 2026-11-09 `ind_close_all_09112026.csv` | yes |
| raw_market/nse_integrated_equities | 0 | 0.00 | - | yes |
| raw_market/nse_integrated_sme | 0 | 0.00 | - | yes |
| raw_market/nse_part_oi | 0 | 0.00 | - | yes |
| raw_market/nse_part_vol | 0 | 0.00 | - | yes |
| raw_market/nse_pit_gg | 0 | 0.00 | - | yes |
| raw_market/nse_pit_gg_sme | 0 | 0.00 | - | yes |
| raw_market/nse_pit_gg_xml | 0 | 0.00 | - | yes |
| raw_market/nse_results_xbrl | 0 | 0.00 | - | yes |
| raw_market/nse_sast | 0 | 0.00 | - | yes |
| raw_market/nse_short | 0 | 0.00 | - | yes |
| raw_market/nse_shp_index | 0 | 0.00 | - | yes |
| rbi | 0 | 0.00 | - | yes |
| reddit | 0 | 0.00 | - | yes |
| results_notes_refetch | 0 | 0.00 | - | yes |
| results_pdfs | 0 | 0.00 | - | yes |
| runners | 0 | 0.00 | - | yes |
| tax_sources | 0 | 0.00 | - | yes |
| transcripts_raw | 17 | 0.01 | 2026-11-09 `sha_index.db` | yes |
| user_research | 803 | 32.77 | 2026-11-02 `LISTENING_CHECK.md` | yes |
| user_research_drive | 236 | 0.60 | 2026-10-26 `_native_blocked.txt` | yes |
| vahan | 0 | 0.00 | - | yes |
