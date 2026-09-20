-- ====================================================================
-- Master Database Schema: equity_intelligence.db
-- Supports Phase 1 Ingestion, Fundamentals, Delivery Momentum, 
-- Forensic Solvency, Insider Trading, and Multi-Factor Screening.
-- ====================================================================

-- 1. Master Company Lookup Table
CREATE TABLE IF NOT EXISTS master_companies (
    isin TEXT PRIMARY KEY,
    nse_symbol TEXT UNIQUE,
    bse_code TEXT UNIQUE,
    company_name TEXT NOT NULL,
    industry TEXT,
    sector TEXT,
    market_cap_tier TEXT CHECK(market_cap_tier IN ('LARGE', 'MID', 'SMALL', 'MICRO')),
    is_fno_eligible BOOLEAN DEFAULT 0,
    is_nifty50 BOOLEAN DEFAULT 0,
    is_nifty100 BOOLEAN DEFAULT 0,
    is_nifty200 BOOLEAN DEFAULT 0,
    is_nifty500 BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Daily Price Action, Volume & Delivery Position (Layer 2)
CREATE TABLE IF NOT EXISTS daily_price_delivery (
    date DATE NOT NULL,
    symbol TEXT NOT NULL,
    isin TEXT NOT NULL,
    series TEXT DEFAULT 'EQ',
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    prev_close REAL NOT NULL,
    change_pct REAL NOT NULL,
    total_volume INTEGER NOT NULL,
    turnover_lacs REAL,
    num_trades INTEGER,
    deliverable_volume INTEGER NOT NULL,
    delivery_pct REAL NOT NULL,
    delivery_spike_ratio REAL,        -- Deliverable Volume / 20-Day SMA(Deliverable Volume)
    delivery_conviction_score REAL,   -- delivery_spike_ratio * delivery_pct
    sma_20 REAL,
    sma_50 REAL,
    sma_200 REAL,
    rsi_14 REAL,
    high_52w REAL,
    low_52w REAL,
    distance_from_52w_high_pct REAL,
    PRIMARY KEY (date, symbol),
    FOREIGN KEY (isin) REFERENCES master_companies(isin)
);

-- 3. Quarterly Financial Disclosures (Layer 1)
CREATE TABLE IF NOT EXISTS quarterly_financials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isin TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quarter_end_date DATE NOT NULL,   -- e.g. '2026-06-30'
    financial_year TEXT NOT NULL,     -- e.g. 'FY27-Q1' or 'Jun 2026'
    revenue_inr_cr REAL,
    ebitda_inr_cr REAL,
    ebitda_margin_pct REAL,
    net_profit_inr_cr REAL,
    pat_margin_pct REAL,
    eps_inr REAL,
    yoy_revenue_growth_pct REAL,
    yoy_pat_growth_pct REAL,
    qoq_revenue_growth_pct REAL,
    qoq_pat_growth_pct REAL,
    xbrl_file_path TEXT,
    concall_pdf_path TEXT,
    investor_presentation_path TEXT,
    has_concall_transcript BOOLEAN DEFAULT 0,
    source TEXT DEFAULT 'yfinance',   -- provenance: yfinance | nse_official | bse_official | fixture
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (isin) REFERENCES master_companies(isin),
    UNIQUE(isin, quarter_end_date)
);

-- 4. Annual Financials & Balance Sheet Ratios
CREATE TABLE IF NOT EXISTS annual_financials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isin TEXT NOT NULL,
    symbol TEXT NOT NULL,
    fiscal_year TEXT NOT NULL,        -- e.g. 'FY26', 'Mar 2026'
    revenue_inr_cr REAL,
    ebitda_inr_cr REAL,
    net_profit_inr_cr REAL,
    eps_inr REAL,
    opm_pct REAL,
    npm_pct REAL,
    roce_pct REAL,
    roe_pct REAL,
    debt_inr_cr REAL,
    equity_inr_cr REAL,
    debt_to_equity REAL,
    interest_coverage REAL,
    operating_cash_flow_inr_cr REAL,
    free_cash_flow_inr_cr REAL,
    source TEXT DEFAULT 'yfinance',   -- provenance: yfinance | nse_official | bse_official | fixture
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (isin) REFERENCES master_companies(isin),
    UNIQUE(isin, fiscal_year)
);

-- 5. Forensic Solvency & Governance Metrics
CREATE TABLE IF NOT EXISTS company_forensic_health (
    isin TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    fiscal_year TEXT NOT NULL,
    promoter_holding_pct REAL NOT NULL DEFAULT 0.0,
    promoter_pledge_pct REAL NOT NULL DEFAULT 0.0,
    fii_holding_pct REAL DEFAULT 0.0,
    dii_holding_pct REAL DEFAULT 0.0,
    public_holding_pct REAL DEFAULT 0.0,
    interest_coverage_ratio REAL NOT NULL DEFAULT 0.0,
    debt_to_equity_ratio REAL NOT NULL DEFAULT 0.0,
    market_cap_inr_cr REAL DEFAULT 0.0,
    pe_ratio REAL DEFAULT 0.0,
    pb_ratio REAL DEFAULT 0.0,
    dividend_yield_pct REAL DEFAULT 0.0,
    altman_z_score REAL,
    auditor_name TEXT,
    has_qualified_audit_opinion BOOLEAN DEFAULT 0,
    related_party_tx_pct_revenue REAL DEFAULT 0.0,
    is_solvency_approved BOOLEAN DEFAULT 1,
    solvency_disqualification_reasons TEXT,
    last_evaluated_date DATE NOT NULL,
    FOREIGN KEY (isin) REFERENCES master_companies(isin)
);

-- 6. SEBI Insider Trading (PIT) & Promoter Buys
CREATE TABLE IF NOT EXISTS insider_trades (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    isin TEXT NOT NULL,
    acquirer_name TEXT NOT NULL,
    category_of_person TEXT NOT NULL, -- 'PROMOTER', 'PROMOTER_GROUP', 'DIRECTOR', 'KMP'
    transaction_type TEXT NOT NULL,   -- 'BUY', 'SELL', 'PLEDGE', 'REVOCATION'
    num_shares INTEGER NOT NULL,
    value_inr_lacs REAL NOT NULL,
    mode_of_acquisition TEXT,        -- 'OPEN_MARKET', 'OFF_MARKET', 'PREFERENTIAL'
    acquisition_date DATE NOT NULL,
    intimation_date DATE NOT NULL,
    FOREIGN KEY (isin) REFERENCES master_companies(isin)
);

-- 7. Daily Bulk & Block Deals
CREATE TABLE IF NOT EXISTS bulk_block_deals (
    id TEXT PRIMARY KEY,
    deal_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    client_name TEXT NOT NULL,
    deal_type TEXT CHECK(deal_type IN ('BULK', 'BLOCK')),
    buy_sell TEXT CHECK(buy_sell IN ('BUY', 'SELL')),
    quantity INTEGER NOT NULL,
    trade_price REAL NOT NULL,
    is_marquee_institution BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 8. Official NSE Sector & Index Breadth
CREATE TABLE IF NOT EXISTS nse_index_breadth (
    date DATE NOT NULL,
    index_name TEXT NOT NULL,          -- 'Nifty 50', 'Nifty Next 50', 'Nifty 100', 'Nifty 200', 'Nifty Auto'
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    change_pct REAL NOT NULL,
    points_change REAL,
    volume INTEGER,
    turnover_cr REAL,
    advances_count INTEGER DEFAULT 0,
    declines_count INTEGER DEFAULT 0,
    advance_decline_ratio REAL DEFAULT 1.0,
    pe_ratio REAL,
    pb_ratio REAL,
    dividend_yield REAL,
    PRIMARY KEY(date, index_name)
);

-- 9. Dynamic Distilled Parameter Definitions (Module 07)
CREATE TABLE IF NOT EXISTS dynamic_parameter_definitions (
    parameter_key TEXT PRIMARY KEY,       -- e.g., 'cyclicality_profile', 'business_sensitivities'
    display_name TEXT NOT NULL,
    data_type TEXT NOT NULL,              -- 'JSON', 'FLOAT', 'STRING', 'BOOLEAN'
    description TEXT,
    category TEXT NOT NULL,               -- 'CYCLICALITY', 'BUSINESS_MODEL', 'GOVERNANCE', 'MACRO'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 10. Distilled Company Parameters (Extensible Entity-Attribute-Value + JSON1 Store)
CREATE TABLE IF NOT EXISTS company_distilled_parameters (
    isin TEXT NOT NULL,
    symbol TEXT NOT NULL,
    parameter_key TEXT NOT NULL,
    value_json TEXT NOT NULL,             -- JSON string containing structured parameter payload
    confidence_score REAL DEFAULT 1.0,    -- LLM distillation confidence (0.0 to 1.0)
    source_document_ref TEXT,             -- e.g., "Concall_FY26Q1_P14", "AnnualReport_FY25"
    last_updated_date DATE NOT NULL,
    PRIMARY KEY (isin, parameter_key),
    FOREIGN KEY (isin) REFERENCES master_companies(isin),
    FOREIGN KEY (parameter_key) REFERENCES dynamic_parameter_definitions(parameter_key)
);

-- 11. EOD Multi-Factor Scrip Calls & Screening Output
CREATE TABLE IF NOT EXISTS eod_scrip_calls (
    date DATE NOT NULL,
    symbol TEXT NOT NULL,
    isin TEXT NOT NULL,
    composite_rank INTEGER NOT NULL,
    technical_score REAL NOT NULL,       -- 0 to 100
    fundamental_score REAL NOT NULL,     -- 0 to 100
    alt_sentiment_score REAL NOT NULL,   -- 0 to 100
    composite_score REAL NOT NULL,       -- Weighted Aggregate
    current_market_price REAL NOT NULL,
    recommended_entry_range TEXT,
    target_price REAL,
    stop_loss REAL,
    risk_reward_ratio REAL,
    conviction_level TEXT CHECK(conviction_level IN ('HIGH_CONVICTION', 'MODERATE', 'SPECULATIVE')),
    is_solvency_approved BOOLEAN DEFAULT 1,
    delivery_spike_ratio REAL,
    delivery_conviction_score REAL,
    yoy_revenue_growth_pct REAL,
    yoy_pat_growth_pct REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(date, symbol),
    FOREIGN KEY(isin) REFERENCES master_companies(isin)
);

-- 12. Document & Announcements Metadata Registry
CREATE TABLE IF NOT EXISTS corporate_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isin TEXT NOT NULL,
    symbol TEXT NOT NULL,
    doc_type TEXT NOT NULL,              -- 'CONCALL_TRANSCRIPT', 'INVESTOR_PRESENTATION', 'ANNUAL_REPORT', 'ANNOUNCEMENT', 'FINANCIAL_RESULT', 'OFFER_DOCUMENT' (SEBI DRHP/Prospectus)
    title TEXT NOT NULL,
    doc_date DATE NOT NULL,
    source_url TEXT,
    source TEXT,                       -- provenance: 'bse_official' | 'nse_official' | 'screener_discovery'
    discovery_source TEXT,             -- where the link was discovered: 'screener_discovery' etc.
    local_file_path TEXT,
    file_size_bytes INTEGER,
    sha256_hash TEXT,
    is_processed BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (isin) REFERENCES master_companies(isin),
    UNIQUE(source_url)   -- idempotent upsert key for repository.upsert_corporate_documents
);

-- 12b. Corporate Actions Registry (official NSE corporate-actions feed)
CREATE TABLE IF NOT EXISTS corporate_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isin TEXT NOT NULL,
    symbol TEXT NOT NULL,
    company_name TEXT,
    subject TEXT,                      -- raw NSE subject line
    action_type TEXT NOT NULL,         -- normalized: DIVIDEND, BONUS, SPLIT, RIGHTS,
                                        -- BUYBACK, MERGER, DEMERGER, INTEREST, AGM, OTHER
    ex_date DATE,
    rec_date DATE,
    bc_start_date DATE,                -- book-closure start
    bc_end_date DATE,                  -- book-closure end
    nd_start_date DATE,                -- no-delivery start
    nd_end_date DATE,                  -- no-delivery end
    broadcast_date DATE,
    face_value REAL,
    series TEXT,
    industry TEXT,
    source TEXT DEFAULT 'nse_official',
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(isin, subject, ex_date, action_type)
);

CREATE INDEX IF NOT EXISTS idx_ca_isin ON corporate_actions(isin);
CREATE INDEX IF NOT EXISTS idx_ca_symbol ON corporate_actions(symbol);
CREATE INDEX IF NOT EXISTS idx_ca_type ON corporate_actions(action_type);

-- 12c. Corporate Status Flags (delisting / suspension / NCLT-CIRP insolvency)
CREATE TABLE IF NOT EXISTS corporate_status_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isin TEXT,
    symbol TEXT NOT NULL,
    status_type TEXT NOT NULL,        -- DELISTED | SUSPENDED | NCLT_CIRP | INSOLVENCY_RISK
    source TEXT NOT NULL,             -- nse_official | bse_official | announcement_scan | derived
    detail TEXT,                       -- free-text reason / proceeding reference
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, status_type, source)
);

CREATE INDEX IF NOT EXISTS idx_csf_symbol ON corporate_status_flags(symbol);
CREATE INDEX IF NOT EXISTS idx_csf_type ON corporate_status_flags(status_type);

-- 13. Knowledge Graph and Macro Event Intelligence
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,
    name TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS graph_causal_edges (
    edge_id TEXT PRIMARY KEY,
    source_node_id TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    impact_direction TEXT NOT NULL,
    elasticity_score REAL,
    transmission_mechanism TEXT NOT NULL,
    evidence_document_ref TEXT,
    confidence_score REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_node_id) REFERENCES graph_nodes(node_id),
    FOREIGN KEY(target_node_id) REFERENCES graph_nodes(node_id)
);

CREATE TABLE IF NOT EXISTS macro_events (
    event_id TEXT PRIMARY KEY,
    event_name TEXT NOT NULL,
    category TEXT NOT NULL,
    event_date DATE NOT NULL,
    raw_document_path TEXT,
    summary TEXT NOT NULL,
    affected_nodes_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 14. Local Inbox Ingestion Manifest
CREATE TABLE IF NOT EXISTS inbox_ingestion_manifest (
    file_hash TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    detected_entity_type TEXT DEFAULT 'UNKNOWN',
    target_entity_key TEXT,
    summary TEXT,
    extracted_parameters_json TEXT,
    associated_graph_nodes_json TEXT,
    processed_file_path TEXT NOT NULL,
    ingested_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 15. Full-text searchable document chunks
CREATE VIRTUAL TABLE IF NOT EXISTS intelligence_fts USING fts5(
    chunk_id UNINDEXED,
    symbol,
    isin,
    source_type UNINDEXED,
    document_date UNINDEXED,
    document_text,
    tokenize='porter unicode61'
);

-- ====================================================================
-- Performance Indexes for Rapid Multi-Factor & Time-Series Scanning
-- ====================================================================
CREATE INDEX IF NOT EXISTS idx_master_sym ON master_companies(nse_symbol);
CREATE INDEX IF NOT EXISTS idx_master_nifty200 ON master_companies(is_nifty200);
CREATE INDEX IF NOT EXISTS idx_price_date ON daily_price_delivery(date);
CREATE INDEX IF NOT EXISTS idx_price_sym_date ON daily_price_delivery(symbol, date DESC);
CREATE INDEX IF NOT EXISTS idx_price_spike ON daily_price_delivery(date, delivery_spike_ratio DESC);
CREATE INDEX IF NOT EXISTS idx_price_conviction ON daily_price_delivery(date, delivery_conviction_score DESC);
CREATE INDEX IF NOT EXISTS idx_quarterly_sym_date ON quarterly_financials(symbol, quarter_end_date DESC);
CREATE INDEX IF NOT EXISTS idx_annual_sym_fy ON annual_financials(symbol, fiscal_year DESC);
CREATE INDEX IF NOT EXISTS idx_forensic_solvency ON company_forensic_health(is_solvency_approved);
CREATE INDEX IF NOT EXISTS idx_insider_sym_date ON insider_trades(symbol, acquisition_date DESC);
CREATE INDEX IF NOT EXISTS idx_deals_sym_date ON bulk_block_deals(symbol, deal_date DESC);
CREATE INDEX IF NOT EXISTS idx_docs_sym_date ON corporate_documents(symbol, doc_date DESC);

-- Document chunk search and local drop-in ingestion state.
CREATE VIRTUAL TABLE IF NOT EXISTS intelligence_fts USING fts5(
    chunk_id UNINDEXED, symbol, isin, source_type, document_date, document_text,
    tokenize='porter unicode61'
);
CREATE TABLE IF NOT EXISTS inbox_ingestion_manifest (
    file_hash TEXT PRIMARY KEY, original_filename TEXT NOT NULL, file_type TEXT NOT NULL,
    detected_entity_type TEXT DEFAULT 'UNKNOWN', target_entity_key TEXT, summary TEXT DEFAULT '',
    extracted_parameters_json TEXT, associated_graph_nodes_json TEXT,
    processed_file_path TEXT NOT NULL, ingested_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 16. Telegram Forum Posts & Transcribed OCR Data (Layer 3)
CREATE TABLE IF NOT EXISTS telegram_posts (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    channel_title TEXT NOT NULL,
    thread_topic_id INTEGER DEFAULT 0,
    thread_topic_name TEXT,
    message_id INTEGER NOT NULL,
    raw_message_text TEXT,
    has_media BOOLEAN DEFAULT 0,
    media_file_path TEXT,
    ocr_extracted_text TEXT,
    detected_symbols_json TEXT,
    button_links_json TEXT,
    post_timestamp TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 17. FinanciallyFree Portal Sector & Breadth Snapshot (Layer 3)
CREATE TABLE IF NOT EXISTS financially_free_breadth (
    date DATE NOT NULL,
    sector_name TEXT NOT NULL,
    advances_count INTEGER NOT NULL,
    declines_count INTEGER NOT NULL,
    advance_decline_ratio REAL NOT NULL,
    sector_momentum_score REAL,
    top_gainers_json TEXT,
    top_losers_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(date, sector_name)
);

CREATE INDEX IF NOT EXISTS idx_tg_post_time ON telegram_posts(post_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tg_channel_msg ON telegram_posts(channel_id, message_id);
CREATE INDEX IF NOT EXISTS idx_ff_date ON financially_free_breadth(date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_isin_date ON daily_price_delivery(isin, date DESC);
CREATE INDEX IF NOT EXISTS idx_quarterly_isin_date ON quarterly_financials(isin, quarter_end_date DESC);
CREATE INDEX IF NOT EXISTS idx_annual_isin_fy ON annual_financials(isin, fiscal_year DESC);
CREATE INDEX IF NOT EXISTS idx_insider_isin_date ON insider_trades(isin, acquisition_date DESC);
CREATE INDEX IF NOT EXISTS idx_deals_date ON bulk_block_deals(deal_date DESC);
CREATE INDEX IF NOT EXISTS idx_deals_type_date ON bulk_block_deals(deal_type, deal_date DESC);
CREATE INDEX IF NOT EXISTS idx_distilled_sym_key ON company_distilled_parameters(symbol, parameter_key);
CREATE INDEX IF NOT EXISTS idx_distilled_isin ON company_distilled_parameters(isin);
CREATE INDEX IF NOT EXISTS idx_edge_source ON graph_causal_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_edge_target ON graph_causal_edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_edge_type ON graph_causal_edges(relationship_type);
CREATE INDEX IF NOT EXISTS idx_macro_event_date ON macro_events(event_date DESC);
CREATE INDEX IF NOT EXISTS idx_macro_event_category_date ON macro_events(category, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_manifest_entity ON inbox_ingestion_manifest(detected_entity_type, target_entity_key);

-- ====================================================================
-- 18. Raw Document Registry (audit trail / replay source for macro PDFs)
-- Second-tier peer data: Central/State Budgets, PIB circulars, RBI reports.
-- Mirrors postgres_schema.sql raw_documents; source_type enum includes:
--   Union_Budget, Economic_Survey, State_Budget_UP, State_Budget_Tamil_Nadu,
--   State_Budget_Maharashtra, State_Budget_Karnataka, State_Budget_Telangana,
--   State_Budget_Gujarat, State_Budget_Haryana, State_Budget_Andhra_Pradesh,
--   PIB_Circular, RBI_Annual_Report, RBI_Financial_Stability_Report
-- ====================================================================
CREATE TABLE IF NOT EXISTS raw_documents (
    doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    published_date TEXT NOT NULL,
    fiscal_period TEXT,
    source_url TEXT UNIQUE,
    creator_or_ministry TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    sha256_hash TEXT UNIQUE,
    local_file_path TEXT,
    file_size_bytes INTEGER
);

CREATE INDEX IF NOT EXISTS idx_rawdoc_hash ON raw_documents(sha256_hash);
CREATE INDEX IF NOT EXISTS idx_rawdoc_source_type ON raw_documents(source_type);
CREATE INDEX IF NOT EXISTS idx_rawdoc_published ON raw_documents(published_date DESC);

-- ====================================================================
-- 19b. Regulatory Political Risks (policy peer) — SQLite fallback mirror of postgres_schema.sql
-- Coverage status: 'mapped' = has ENI numeric, 'no_template' = sentinel coverage-only,
-- 'unknown' = no row. Sentinel policy_name='__NO_POLICY_TEMPLATE__' with NULL impacts.
-- ====================================================================
CREATE TABLE IF NOT EXISTS regulatory_political_risks (
    risk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    ticker TEXT,
    isin TEXT,
    symbol TEXT,
    policy_name TEXT NOT NULL,
    risk_type TEXT,
    factor_type TEXT,
    severity_score REAL,
    probability REAL,
    net_impact_score REAL,
    time_horizon TEXT,
    coverage_status TEXT CHECK (coverage_status IN ('mapped','no_template','unknown')) DEFAULT 'mapped',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, policy_name)
);
CREATE INDEX IF NOT EXISTS idx_regpol_symbol ON regulatory_political_risks(symbol);
CREATE INDEX IF NOT EXISTS idx_regpol_isin ON regulatory_political_risks(isin);
CREATE INDEX IF NOT EXISTS idx_regpol_coverage ON regulatory_political_risks(coverage_status);
CREATE INDEX IF NOT EXISTS idx_regpol_net ON regulatory_political_risks(net_impact_score);

-- ====================================================================
-- 19. Pruning / Decay Config (Pillar 2) — SQLite parity with postgres_schema.sql
-- Half-life categories control embedding decay + structural-milestone survival.
-- ====================================================================
CREATE TABLE IF NOT EXISTS pruning_decay_config (
    category TEXT PRIMARY KEY,
    half_life_months REAL NOT NULL,
    lambda REAL,
    significance_floor REAL DEFAULT 5.0,
    prob_cutoff REAL DEFAULT 0.08
);

-- Seed macro + policy decay categories (idempotent; base 3 rows managed by
-- pruning_engine.ensure_pruning_schema). Lambda is left NULL here and
-- back-filled by the migration helper in database.py so it matches the
-- computed LN(2)/half_life value exactly.
INSERT OR IGNORE INTO pruning_decay_config (category, half_life_months) VALUES
    ('State Budget', 12),
    ('PIB Circular', 3),
    ('RBI Report / Economic Survey', 6),
    ('Economic Survey', 12),
    ('Union Budget / Tax Reform', 12);

-- ====================================================================
-- 20. Wave B — Model-validation loop (prediction scoring + calibration)
-- Additive only. Scored by reality_engine/processing/validation_harness.py.
-- lens_family NULL = whole-cohort row; set = per-dominant-lens bucket row.
-- investor_majority 'all' = whole-cohort row; else per-holder-cohort split.
-- thesis_hit_rate/thesis_n are NULL except on whole-cohort ('all' investor,
-- NULL lens) rows where alpha theses with entry/target/SL were available.
-- model_lens_weight_proposals holds fit_lens_weights() proposals only;
-- model_explainer_rankings is NEVER auto-updated (apply_calibration is
-- a deliberate later call via EnsembleRanker.upsert_ranking).
-- ====================================================================
CREATE TABLE IF NOT EXISTS model_validation_scores (
    score_id INTEGER PRIMARY KEY AUTOINCREMENT,
    asof_date DATE NOT NULL,
    horizon_days INTEGER NOT NULL,
    mode TEXT NOT NULL,
    lens_family TEXT,
    regime_tag TEXT NOT NULL DEFAULT 'unknown',
    investor_majority TEXT NOT NULL DEFAULT 'all',
    n INTEGER NOT NULL DEFAULT 0,
    hit_rate REAL,
    mean_fwd_ret REAL,
    universe_mean_ret REAL,
    ic REAL,
    thesis_hit_rate REAL,
    thesis_n INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(asof_date, horizon_days, mode, lens_family, regime_tag, investor_majority)
);

CREATE INDEX IF NOT EXISTS idx_val_asof ON model_validation_scores(asof_date DESC);
CREATE INDEX IF NOT EXISTS idx_val_mode_horizon ON model_validation_scores(mode, horizon_days);
CREATE INDEX IF NOT EXISTS idx_val_lens ON model_validation_scores(lens_family);
CREATE INDEX IF NOT EXISTS idx_val_regime ON model_validation_scores(regime_tag);

CREATE TABLE IF NOT EXISTS model_lens_weight_proposals (
    proposal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    regime_tag TEXT NOT NULL,
    investor_majority TEXT NOT NULL DEFAULT 'all',
    lens_family TEXT NOT NULL,
    weight REAL NOT NULL,
    basis_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(regime_tag, investor_majority, lens_family)
);
