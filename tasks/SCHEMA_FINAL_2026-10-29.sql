-- =====================================================================================
-- REALITY ENGINE - SCHEMA FINAL (2026-10-29)
--
-- Authority: tasks/FRAMEWORK.md and tasks/AGENTS_GOLDEN_RULE (step 3). This file
-- consolidates tasks/arch_v3/SCHEMA_V3.sql, tasks/arch_v3_chunks/INDEX_SPEC.md,
-- tasks/RIPPLE_SCHEMA_REQUIREMENTS_2026-10-28.md,
-- tasks/LABELS_TAGGING_PLAN_2026-10-27.md, tasks/QUERY_TEMPLATES_2026-10-27.md and
-- tasks/ARCHITECTURE_OVERHAUL_2026-10-27.md against the 1,073-case master bank.
-- The design rationale, the per-case classification and the build order are in
-- tasks/SCHEMA_FINAL_2026-10-29.md.
--
-- RUN (verification, one in-memory database with ten attached domains):
--     python -c "import sqlite3;c=sqlite3.connect(':memory:');\
--       c.executescript(open('tasks/SCHEMA_FINAL_2026-10-29.sql',encoding='utf-8').read());print('ok')"
--
-- PRODUCTION: the ten ATTACH lines below are the verification harness. In production
-- each section is applied to its own file (one writer per file, WAL mode):
--     equity_intelligence.db, results_xbrl.db, ar_facts.db, deck_figures.db,
--     concall_facts.db, bse_announcements.db .......... live stores, DDL copied from
--                                                       sqlite_master on 2026-10-29
--     snapshots/truth_<date>.duckdb .................... dated DuckDB snapshot (logical
--                                                       mirror declared for tests; physical
--                                                       file is columnar and has no indexes)
--     market_state.db .................................. layer-2/3/4 state (pilot copy:
--                                                       data/pilot/pilot60/market_state_pilot.db,
--                                                       data/pilot/macro_all.db)
--     metric_state.db .................................. structured numbers (pilot copy:
--                                                       data/pilot/pilot60/facts_pilot.db)
--     chunks_v3.db ..................................... text layer (pilot copy:
--                                                       data/pilot/pilot60/chunks_v3_pilot.db)
--
-- CONVENTIONS
--   * every TIMESTAMP is ISO-8601 text in IST; the DuckDB snapshot adds known_at_utc
--   * known_at = first instant the market could see the row (PIT key); known_at_src
--     names the record it came from (bse_dissem|nse_dissem|filing_ts|letterhead|
--     folder_name|drive_btime|telegram|upload|session_close)
--   * pit_conf in [0,1]: 1.0 exact exchange timestamp, 0.8 date only, 0.6 inferred
--   * 15:30 IST day-0 rule: a filing after 15:30 IST belongs to the next session
--     (event_day0.session_0 / offset / in_session)
--   * EVERY derived table carries known_at even when its source has none; the build
--     stamps it from the filing record, never from the crawl date
--   * no consensus estimates, no named-investor holdings: see the NID footer
-- =====================================================================================

PRAGMA foreign_keys = OFF;

-- =====================================================================================
-- 0. DOMAINS (verification harness; replace with the production file names)
-- =====================================================================================

ATTACH DATABASE ':memory:' AS equity_intelligence;   -- production: reality_engine/data/equity_intelligence.db

ATTACH DATABASE ':memory:' AS results_xbrl;   -- production: reality_engine/data/results_xbrl.db

ATTACH DATABASE ':memory:' AS ar_facts;   -- production: reality_engine/data/ar_facts.db

ATTACH DATABASE ':memory:' AS deck_figures;   -- production: reality_engine/data/deck_figures.db

ATTACH DATABASE ':memory:' AS concall_facts;   -- production: reality_engine/data/concall_facts.db

ATTACH DATABASE ':memory:' AS bse_announcements;   -- production: reality_engine/data/bse_announcements.db

ATTACH DATABASE ':memory:' AS truth_duckdb;   -- production: reality_engine/data/snapshots/truth_<date>.duckdb (DuckDB)

ATTACH DATABASE ':memory:' AS market_state;   -- production: reality_engine/data/market_state.db

ATTACH DATABASE ':memory:' AS metric_state;   -- production: reality_engine/data/metric_state.db

ATTACH DATABASE ':memory:' AS chunks_v3;   -- production: reality_engine/data/chunks_v3.db


-- =====================================================================================
-- 1. LIVE STORES - canonical DDL copied from sqlite_master (2026-10-29).
--    These are built and owned by the ingestion jobs; the query layer reads them.
-- =====================================================================================


-- ------------------------------------------------------------------------------------
-- 1.1 equity_intelligence  (equity_intelligence.db)
-- ------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS equity_intelligence.master_companies (
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
, listing_source TEXT CHECK (listing_source IN ('NSE','DUAL','BSE_ONLY')), is_screenable INTEGER DEFAULT 1);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_master_nifty200 ON master_companies(is_nifty200);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_master_sym ON master_companies(nse_symbol);

CREATE TABLE IF NOT EXISTS equity_intelligence.security_master (isin TEXT PRIMARY KEY, issuer TEXT, name TEXT, nse_symbol TEXT, bse_code TEXT,
    bse_symbol TEXT, bse_status TEXT, segment TEXT, nse_listing_date TEXT, first_trade TEXT, last_trade TEXT,
    last_seen_nse TEXT, last_seen_bse TEXT, in_master_companies INTEGER, source TEXT);

CREATE TABLE IF NOT EXISTS equity_intelligence.symbol_isin_history (exchange TEXT, symbol TEXT, isin TEXT, first_date TEXT, last_date TEXT, n_days INTEGER,
    PRIMARY KEY (exchange, symbol, isin, first_date));

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_sih_isin ON symbol_isin_history(isin);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_sih_symbol ON symbol_isin_history(exchange, symbol, first_date);

CREATE TABLE IF NOT EXISTS equity_intelligence.company_industry (isin TEXT, symbol TEXT PRIMARY KEY, series TEXT, macro TEXT,
    sector TEXT, industry TEXT, basic_industry TEXT, index_list TEXT, listing_date TEXT, fetched_at TEXT);

CREATE TABLE IF NOT EXISTS equity_intelligence.daily_price_delivery (
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

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_daily_isin_date ON daily_price_delivery(isin, date DESC);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_price_conviction ON daily_price_delivery(date, delivery_conviction_score DESC);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_price_date ON daily_price_delivery(date);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_price_spike ON daily_price_delivery(date, delivery_spike_ratio DESC);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_price_sym_date ON daily_price_delivery(symbol, date DESC);

CREATE TABLE IF NOT EXISTS equity_intelligence.mkt_nse_full_daily (
    date TEXT NOT NULL, symbol TEXT NOT NULL, series TEXT NOT NULL,
    prev_close REAL, open REAL, high REAL, low REAL, last REAL, close REAL, avg_price REAL,
    volume INTEGER, turnover_lacs REAL, num_trades INTEGER, deliverable_qty INTEGER, delivery_pct REAL,
    PRIMARY KEY (date, symbol, series));

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_mkt_nse_full_cover ON mkt_nse_full_daily(symbol, date, series, open, high, low, close, volume, turnover_lacs, delivery_pct);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_mkt_nse_full_symbol ON mkt_nse_full_daily(symbol, date);

CREATE TABLE IF NOT EXISTS equity_intelligence.mkt_bse_eq_daily (
    date TEXT NOT NULL, sc_code TEXT NOT NULL, isin TEXT, symbol TEXT, name TEXT,
    sc_group TEXT, sc_type TEXT,
    open REAL, high REAL, low REAL, close REAL, last REAL, prev_close REAL,
    num_trades INTEGER, volume INTEGER, turnover_inr REAL, file_format TEXT,
    PRIMARY KEY (date, sc_code));

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_mkt_bse_eq_cover ON mkt_bse_eq_daily(isin, date, open, high, low, close, volume, turnover_inr);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_mkt_bse_eq_isin ON mkt_bse_eq_daily(isin, date);

CREATE TABLE IF NOT EXISTS equity_intelligence.price_bands (date TEXT, symbol TEXT, series TEXT, band TEXT, remarks TEXT,
    PRIMARY KEY (date, symbol, series));

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_band_sym ON price_bands(symbol, date);

CREATE TABLE IF NOT EXISTS equity_intelligence.circuit_hits (date TEXT, symbol TEXT, series TEXT, high_low TEXT, PRIMARY KEY (date, symbol, series));

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_circuit_sym ON circuit_hits(symbol, date);

CREATE TABLE IF NOT EXISTS equity_intelligence.corporate_actions (
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

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_ca_isin ON corporate_actions(isin);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_ca_symbol ON corporate_actions(symbol);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_ca_type ON corporate_actions(action_type);

CREATE TABLE IF NOT EXISTS equity_intelligence.corporate_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isin TEXT NOT NULL,
    symbol TEXT NOT NULL,
    doc_type TEXT NOT NULL,              -- 'CONCALL_TRANSCRIPT', 'INVESTOR_PRESENTATION', 'ANNUAL_REPORT', 'ANNOUNCEMENT'
    title TEXT NOT NULL,
    doc_date DATE NOT NULL,
    source_url TEXT,
    local_file_path TEXT,
    file_size_bytes INTEGER,
    sha256_hash TEXT,
    is_processed BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, source TEXT, discovery_source TEXT, event_date TEXT, event_source TEXT, doc_version INTEGER DEFAULT 1, call_date TEXT, publication_date TEXT, pit_source TEXT, pit_tier INTEGER, pit_applied_at TEXT, bse_newsid TEXT, bse_dissem_ts TEXT, bse_news_dt TEXT, bse_subcat TEXT, bse_joined_at TEXT, fiscal_period_end TEXT,
    FOREIGN KEY (isin) REFERENCES master_companies(isin)
);

CREATE UNIQUE INDEX IF NOT EXISTS equity_intelligence.idx_corp_docs_source_url ON corporate_documents(source_url);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_corpdocs_event_date ON corporate_documents(event_date);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_corpdocs_pending ON corporate_documents(doc_type, is_processed, local_file_path);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_docs_sym_date ON corporate_documents(symbol, doc_date DESC);

CREATE TABLE IF NOT EXISTS equity_intelligence.raw_documents (
            doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            source_type TEXT NOT NULL,
            published_date TEXT NOT NULL,
            fiscal_period TEXT,
            source_url TEXT,
            creator_or_ministry TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            sha256_hash TEXT UNIQUE,
            local_file_path TEXT,
            file_size_bytes INTEGER
        , is_structural_milestone INTEGER DEFAULT 0, event_date TEXT, event_source TEXT, doc_version INTEGER DEFAULT 1, symbol TEXT, isin TEXT, symbol_source TEXT);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_rawdoc_hash ON raw_documents(sha256_hash);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_rawdoc_published ON raw_documents(published_date DESC);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_rawdoc_source_type ON raw_documents(source_type);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_rawdoc_type_pub ON raw_documents(source_type, published_date DESC);

CREATE UNIQUE INDEX IF NOT EXISTS equity_intelligence.idx_rawdoc_url ON raw_documents(source_url);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_rawdocs_event_date ON raw_documents(event_date);

CREATE TABLE IF NOT EXISTS equity_intelligence.document_chunks (
            chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER REFERENCES raw_documents(doc_id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding TEXT,
            published_date TEXT,
            timestamp_start_sec INTEGER,
            timestamp_end_sec INTEGER,
            sector_id INTEGER,
            industry_id INTEGER,
            symbol TEXT,
            isin TEXT, fiscal_period TEXT, fiscal_confidence REAL, fiscal_source TEXT, event_date TEXT, event_source TEXT, doc_version INTEGER DEFAULT 1,
            UNIQUE(doc_id, chunk_index)
        );

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_chunks_event_date ON document_chunks(event_date);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_chunks_fiscal ON document_chunks(fiscal_period, fiscal_confidence);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_docchunks_doc ON document_chunks(doc_id, chunk_index);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_docchunks_isin ON document_chunks(isin);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_docchunks_noindustry ON document_chunks(symbol) WHERE industry_id IS NULL;

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_docchunks_symbol ON document_chunks(symbol);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_docchunks_symbol_chunk ON document_chunks(symbol, chunk_id);

CREATE VIRTUAL TABLE IF NOT EXISTS equity_intelligence.intelligence_fts USING fts5(
    chunk_id UNINDEXED,
    symbol,
    isin,
    source_type UNINDEXED,
    document_date UNINDEXED,
    document_text,
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS equity_intelligence.policy_events (id INTEGER PRIMARY KEY AUTOINCREMENT, source_kind TEXT, source_id TEXT,
    section INTEGER, published_at TEXT, title TEXT, policy_name TEXT, instrument TEXT, stage TEXT,
    direction_for_industry TEXT, sectors TEXT, companies TEXT, products TEXT, amount_inr_crore REAL, old_value TEXT,
    new_value TEXT, unit TEXT, effective_date TEXT, end_date TEXT, geography TEXT, quote TEXT, quote_ok INTEGER,
    model TEXT, extracted_at TEXT);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_policy_instrument ON policy_events(instrument);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_policy_pub ON policy_events(published_at);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_policy_stage ON policy_events(stage);

CREATE TABLE IF NOT EXISTS equity_intelligence.macro_events (
    event_id TEXT PRIMARY KEY,
    event_name TEXT NOT NULL,
    category TEXT NOT NULL,
    event_date DATE NOT NULL,
    raw_document_path TEXT,
    summary TEXT NOT NULL,
    affected_nodes_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, doc_id INTEGER);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_macro_event_category_date ON macro_events(category, event_date DESC);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_macro_event_date ON macro_events(event_date DESC);

CREATE TABLE IF NOT EXISTS equity_intelligence.annual_financials (
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, source TEXT DEFAULT 'yfinance',
    FOREIGN KEY (isin) REFERENCES master_companies(isin),
    UNIQUE(isin, fiscal_year)
);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_annual_isin_fy ON annual_financials(isin, fiscal_year DESC);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_annual_sym_fy ON annual_financials(symbol, fiscal_year DESC);

CREATE TABLE IF NOT EXISTS equity_intelligence.quarterly_financials (
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, source TEXT DEFAULT 'yfinance',
    FOREIGN KEY (isin) REFERENCES master_companies(isin),
    UNIQUE(isin, quarter_end_date)
);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_quarterly_isin_date ON quarterly_financials(isin, quarter_end_date DESC);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_quarterly_sym_date ON quarterly_financials(symbol, quarter_end_date DESC);

CREATE TABLE IF NOT EXISTS equity_intelligence.shp_index (record_id TEXT PRIMARY KEY, idx TEXT, symbol TEXT, isin TEXT, name TEXT,
    quarter_end TEXT, broadcast_at TEXT, submission_date TEXT, promoter_pct REAL, public_pct REAL, revised TEXT,
    xbrl TEXT, file TEXT);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_shp_isin ON shp_index(isin, quarter_end);

CREATE TABLE IF NOT EXISTS equity_intelligence.shp_facts (file TEXT, context TEXT, concept TEXT, value TEXT, PRIMARY KEY (file, context, concept));

CREATE TABLE IF NOT EXISTS equity_intelligence.insider_trades_v2 (
    source TEXT NOT NULL,
    source_key TEXT PRIMARY KEY,
    symbol TEXT,
    isin TEXT,
    company TEXT,
    person_name TEXT,
    person_category TEXT,
    transaction_type TEXT NOT NULL,
    mode TEXT,
    security_type TEXT,
    qty REAL,
    value_inr REAL,
    before_pct REAL,
    after_pct REAL,
    trade_from TEXT,
    trade_to TEXT,
    intimation_date TEXT,
    trade_from_raw TEXT,
    trade_to_raw TEXT,
    intimation_date_raw TEXT,
    date_flag TEXT,               -- implausible_trade_date / implausible_intimation_date, comma separated
    known_at TEXT,
    is_revision INTEGER NOT NULL DEFAULT 0,
    supersedes TEXT,
    is_superseded INTEGER NOT NULL DEFAULT 0,
    also_on TEXT
);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_itv2_isin ON insider_trades_v2(isin, trade_from);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_itv2_known ON insider_trades_v2(known_at);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_itv2_symbol ON insider_trades_v2(symbol, trade_from);

CREATE TABLE IF NOT EXISTS equity_intelligence.bulk_block_deals (
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
, exchange TEXT, isin TEXT);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_deals_date ON bulk_block_deals(deal_date DESC);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_deals_exchange_date ON bulk_block_deals(exchange, deal_date DESC);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_deals_isin_date ON bulk_block_deals(isin, deal_date DESC);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_deals_sym_date ON bulk_block_deals(symbol, deal_date DESC);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_deals_type_date ON bulk_block_deals(deal_type, deal_date DESC);

CREATE TABLE IF NOT EXISTS equity_intelligence.mkt_fii_dii_cash (
    date TEXT PRIMARY KEY, fii_purchase_cr REAL, fii_sales_cr REAL, fii_net_cr REAL,
    dii_purchase_cr REAL, dii_sales_cr REAL, dii_net_cr REAL,
    nifty_close REAL, nifty_prev_close REAL, nifty_change_pct REAL, source TEXT);

CREATE TABLE IF NOT EXISTS equity_intelligence.mkt_nsdl_fpi_daily (
    date TEXT NOT NULL, asset_class TEXT NOT NULL, route TEXT NOT NULL,
    gross_purchase_cr REAL, gross_sales_cr REAL, net_cr REAL, net_usd_mn REAL, usdinr REAL,
    PRIMARY KEY (date, asset_class, route));

CREATE TABLE IF NOT EXISTS equity_intelligence.mkt_commodity_daily (
    date TEXT NOT NULL, commodity TEXT NOT NULL, ticker TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, adj_close REAL, volume REAL,
    source TEXT, PRIMARY KEY (date, commodity));

CREATE TABLE IF NOT EXISTS equity_intelligence.mkt_nse_index_daily (
    date TEXT NOT NULL, index_name TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, points_change REAL, pct_change REAL,
    volume INTEGER, turnover_cr REAL, pe REAL, pb REAL, div_yield REAL,
    PRIMARY KEY (date, index_name));

CREATE TABLE IF NOT EXISTS equity_intelligence.index_tri (index_name TEXT, date TEXT, tri REAL, price REAL, source TEXT,
    method TEXT, fetched_at TEXT, PRIMARY KEY (index_name, date));

CREATE TABLE IF NOT EXISTS equity_intelligence.index_membership(index_name text, symbol text, isin text, company_name text, industry text,
             as_of text, source text, primary key(index_name, symbol));

CREATE TABLE IF NOT EXISTS equity_intelligence.nse_index_breadth (
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

CREATE TABLE IF NOT EXISTS equity_intelligence.etf_master (isin TEXT PRIMARY KEY, symbol TEXT, first_date TEXT, last_date TEXT, n_days INTEGER,
    scheme_code TEXT, scheme_name TEXT);

CREATE TABLE IF NOT EXISTS equity_intelligence.etf_px (date TEXT, symbol TEXT, isin TEXT, close REAL, volume REAL, value_inr REAL,
    source TEXT, PRIMARY KEY (date, symbol));

CREATE TABLE IF NOT EXISTS equity_intelligence.etf_inav (isin TEXT, date TEXT, underlying TEXT, idx_close REAL, idx_date TEXT, fx REAL, k REAL, inav REAL, close REAL, nav REAL, premium_vs_inav_pct REAL, PRIMARY KEY (isin, date));

CREATE TABLE IF NOT EXISTS equity_intelligence.fund_nav (isin TEXT, date TEXT, nav REAL, scheme_code TEXT, scheme_name TEXT,
    PRIMARY KEY (isin, date));

CREATE TABLE IF NOT EXISTS equity_intelligence.geographic_exposure (
            company_id INTEGER NOT NULL,
            country_id TEXT NOT NULL,
            revenue_share_pct REAL DEFAULT 0.0,
            asset_exposure_pct REAL DEFAULT 0.0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (company_id, country_id)
        );

CREATE TABLE IF NOT EXISTS equity_intelligence.board_meetings (symbol TEXT, isin TEXT, idx TEXT, meeting_date TEXT, purpose TEXT,
    description TEXT, intimated_at TEXT, industry TEXT, attachment TEXT, fetched_at TEXT,
    PRIMARY KEY (symbol, meeting_date, purpose, intimated_at));

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_bm_date ON board_meetings(meeting_date);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_bm_isin ON board_meetings(isin, meeting_date);

CREATE TABLE IF NOT EXISTS equity_intelligence.pib_releases (prid INTEGER PRIMARY KEY, release_date TEXT, posted_at TEXT, ministry TEXT,
    title TEXT, relevant INTEGER, body TEXT, fetched_at TEXT, doc_id INTEGER);

CREATE INDEX IF NOT EXISTS equity_intelligence.idx_pib_date ON pib_releases(release_date);


-- ------------------------------------------------------------------------------------
-- 1.2 results_xbrl  (results_xbrl.db)
-- ------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS results_xbrl.filings (
  file TEXT PRIMARY KEY, taxonomy TEXT, xbrl_url TEXT, isin TEXT, symbol TEXT, scrip_code TEXT, company TEXT,
  index_period TEXT, reporting_quarter TEXT, consolidated TEXT, audited TEXT, period_start TEXT, period_end TEXT,
  fy_start TEXT, fy_end TEXT, board_meeting TEXT, broadcast_ts TEXT, dissem_ts TEXT, filing_ts TEXT,
  audit_opinion TEXT, n_facts INTEGER, status TEXT, parsed_at TEXT);

CREATE INDEX IF NOT EXISTS results_xbrl.ix_filings_isin ON filings(isin, period_end);

CREATE INDEX IF NOT EXISTS results_xbrl.ix_filings_period ON filings(period_end);

CREATE TABLE IF NOT EXISTS results_xbrl.facts (
  file TEXT, concept TEXT, context TEXT, period_start TEXT, period_end TEXT, instant TEXT, value REAL, unit TEXT, decimals TEXT);

CREATE INDEX IF NOT EXISTS results_xbrl.ix_facts_concept ON facts(concept);

CREATE INDEX IF NOT EXISTS results_xbrl.ix_facts_cover ON facts(file, concept, context, value);

CREATE INDEX IF NOT EXISTS results_xbrl.ix_facts_file ON facts(file);

CREATE INDEX IF NOT EXISTS results_xbrl.ix_facts_file_concept ON facts(file, concept, context);


-- ------------------------------------------------------------------------------------
-- 1.3 ar_facts  (ar_facts.db)
-- ------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ar_facts.ar_docs (doc_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, company TEXT, fiscal_year TEXT,
  fiscal_year_source TEXT, filed_at TEXT, filed_at_source TEXT, sha256 TEXT, path TEXT, n_pages INTEGER, n_text_pages INTEGER,
  n_pieces INTEGER, status TEXT, error TEXT, ts TEXT);

CREATE TABLE IF NOT EXISTS ar_facts.ar_facts (doc_id INTEGER, piece INTEGER, isin TEXT, symbol TEXT, fiscal_year TEXT, filed_at TEXT,
  page INTEGER, category TEXT, item TEXT, value_raw TEXT, value REAL, unit TEXT, period TEXT, basis TEXT, quote TEXT,
  model TEXT, value_check TEXT, prompt_version TEXT);

CREATE INDEX IF NOT EXISTS ar_facts.ar_facts_doc ON ar_facts(doc_id, piece);

CREATE INDEX IF NOT EXISTS ar_facts.ar_facts_isin ON ar_facts(isin, fiscal_year);


-- ------------------------------------------------------------------------------------
-- 1.4 deck_figures  (deck_figures.db)
-- ------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS deck_figures.deck_sources (
  source TEXT, source_id TEXT, symbol TEXT, isin TEXT, exch_code TEXT, known_at TEXT, title TEXT, url TEXT,
  local_path TEXT, sha256 TEXT, size_bytes INTEGER, status TEXT, error TEXT, fetched_at TEXT,
  PRIMARY KEY (source, source_id));

CREATE INDEX IF NOT EXISTS deck_figures.ix_deck_sources_isin ON deck_sources(isin, known_at);

CREATE TABLE IF NOT EXISTS deck_figures.pages (
  sha256 TEXT, page_no INTEGER, prompt_version TEXT, doc_id INTEGER, isin TEXT, symbol TEXT, doc_type TEXT,
  known_at TEXT, route TEXT, text_chars INTEGER, text_numbers INTEGER, img_cov REAL,
  primary_recall REAL, second_recall REAL, final_model TEXT, n_facts INTEGER, status TEXT, error TEXT, run_ts TEXT,
  PRIMARY KEY (sha256, page_no, prompt_version));

CREATE INDEX IF NOT EXISTS deck_figures.ix_pages_isin ON pages(isin, known_at);

CREATE TABLE IF NOT EXISTS deck_figures.facts (
  sha256 TEXT, page_no INTEGER, prompt_version TEXT, model TEXT, line_no INTEGER,
  metric TEXT, period TEXT, raw_number TEXT, value REAL, unit TEXT, is_final INTEGER);

CREATE INDEX IF NOT EXISTS deck_figures.ix_facts_page ON facts(sha256, page_no);

CREATE TABLE IF NOT EXISTS deck_figures.outputs (
  sha256 TEXT, page_no INTEGER, prompt_version TEXT, model TEXT, settings TEXT, run_ts TEXT, seconds REAL,
  in_tok INTEGER, out_tok INTEGER, usd REAL, raw_output TEXT,
  PRIMARY KEY (sha256, page_no, prompt_version, model));


-- ------------------------------------------------------------------------------------
-- 1.5 concall_facts  (concall_facts.db)
-- ------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS concall_facts.cc_docs (doc_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, filed_at TEXT, status TEXT,
    model TEXT, key_name TEXT, chars INTEGER, in_tok INTEGER, out_tok INTEGER, cost_usd REAL, seconds REAL,
    checks_json TEXT, raw_json TEXT, error TEXT, run_at TEXT, priority INTEGER,
    period_discussed TEXT, period_q INTEGER, period_fy INTEGER, date_source TEXT);

CREATE INDEX IF NOT EXISTS concall_facts.idx_cc_docs_run ON cc_docs(run_at);

CREATE TABLE IF NOT EXISTS concall_facts.cc_items (doc_id INTEGER, list_name TEXT, idx INTEGER, isin TEXT, filed_at TEXT,
    metric TEXT, value TEXT, unit TEXT, period TEXT, basis TEXT, direction TEXT, firmness TEXT, signal TEXT,
    statement TEXT, quote TEXT, item_json TEXT, PRIMARY KEY (doc_id, list_name, idx));

CREATE INDEX IF NOT EXISTS concall_facts.idx_cc_items_isin ON cc_items(isin, filed_at);


-- ------------------------------------------------------------------------------------
-- 1.6 bse_announcements  (bse_announcements.db)
-- ------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS bse_announcements.ann(NEWSID TEXT PRIMARY KEY,SCRIP_CD,ATTACHMENTNAME,NEWSSUB,HEADLINE,CATEGORYNAME,SUBCATNAME,NEWS_DT,DT_TM,News_submission_dt,DissemDT,QUARTER_ID,Fld_Attachsize,ANNOUNCEMENT_TYPE,symbol TEXT);

CREATE INDEX IF NOT EXISTS bse_announcements.ix_att on ann(ATTACHMENTNAME);


-- =====================================================================================
-- 2. truth_duckdb - the dated read-only DuckDB snapshot (logical mirror).
--    Research and backtests read this; live reads go to the six stores above.
--    No primary keys: the snapshot is an immutable copy with known_at_utc added.
-- =====================================================================================

-- logical mirror of snapshot table px_nse_adj (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.px_nse_adj (
    date                         TEXT,
    symbol                       TEXT,
    series                       TEXT,
    isin                         TEXT,
    open                         REAL,
    high                         REAL,
    low                          REAL,
    close                        REAL,
    prev_close                   REAL,
    volume                       INTEGER,
    value_inr                    REAL,
    num_trades                   INTEGER,
    deliverable_qty              INTEGER,
    delivery_pct                 REAL,
    src                          TEXT,
    entity_id                    TEXT,
    cum_price_factor             REAL,
    cum_div_factor               REAL,
    adj_open                     REAL,
    adj_high                     REAL,
    adj_low                      REAL,
    adj_close                    REAL,
    adj_volume                   REAL,
    tr_close                     REAL
);
-- logical mirror of snapshot table px_bse_adj (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.px_bse_adj (
    date                         TEXT,
    sc_code                      TEXT,
    isin                         TEXT,
    symbol                       TEXT,
    name                         TEXT,
    sc_group                     TEXT,
    open                         REAL,
    high                         REAL,
    low                          REAL,
    close                        REAL,
    prev_close                   REAL,
    volume                       INTEGER,
    value_inr                    REAL,
    num_trades                   INTEGER,
    deliverable_qty              INTEGER,
    delivery_pct                 REAL,
    src                          TEXT,
    entity_id                    TEXT,
    cum_price_factor             REAL,
    cum_div_factor               REAL,
    adj_open                     REAL,
    adj_high                     REAL,
    adj_low                      REAL,
    adj_close                    REAL,
    adj_volume                   REAL,
    tr_close                     REAL
);
-- logical mirror of snapshot table px_daily (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.px_daily (
    exch                         TEXT,
    entity_id                    TEXT,
    date                         TEXT,
    isin                         TEXT,
    symbol                       TEXT,
    segment                      TEXT,
    open                         REAL,
    high                         REAL,
    low                          REAL,
    close                        REAL,
    volume                       INTEGER,
    value_inr                    REAL,
    deliverable_qty              INTEGER,
    delivery_pct                 REAL,
    cum_price_factor             REAL,
    cum_div_factor               REAL,
    adj_open                     REAL,
    adj_high                     REAL,
    adj_low                      REAL,
    adj_close                    REAL,
    adj_volume                   REAL,
    tr_close                     REAL
);
-- logical mirror of snapshot table px_nse (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.px_nse (
    date                         TEXT,
    symbol                       TEXT,
    series                       TEXT,
    isin                         TEXT,
    open                         REAL,
    high                         REAL,
    low                          REAL,
    close                        REAL,
    prev_close                   REAL,
    volume                       INTEGER,
    value_inr                    REAL,
    num_trades                   INTEGER,
    deliverable_qty              INTEGER,
    delivery_pct                 REAL,
    src                          TEXT,
    entity_id                    TEXT
);
-- logical mirror of snapshot table px_bse (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.px_bse (
    date                         TEXT,
    sc_code                      TEXT,
    isin                         TEXT,
    symbol                       TEXT,
    name                         TEXT,
    sc_group                     TEXT,
    open                         REAL,
    high                         REAL,
    low                          REAL,
    close                        REAL,
    prev_close                   REAL,
    volume                       INTEGER,
    value_inr                    REAL,
    num_trades                   INTEGER,
    deliverable_qty              INTEGER,
    delivery_pct                 REAL,
    src                          TEXT,
    entity_id                    TEXT
);
-- logical mirror of snapshot table px_primary_raw (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.px_primary_raw (
    entity_id                    TEXT,
    date                         TEXT,
    close                        REAL,
    open                         REAL,
    exch                         TEXT,
    prev_close                   REAL,
    prev_date                    TEXT
);
-- logical mirror of snapshot table events (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.events (
    isin                         TEXT,
    known_at_utc                 TEXT,
    kind                         TEXT,
    source_ref                   TEXT,
    summary                      TEXT
);
-- logical mirror of snapshot table results_filings (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.results_filings (
    file                         TEXT,
    taxonomy                     TEXT,
    xbrl_url                     TEXT,
    isin                         TEXT,
    symbol                       TEXT,
    scrip_code                   TEXT,
    company                      TEXT,
    index_period                 TEXT,
    reporting_quarter            TEXT,
    consolidated                 TEXT,
    audited                      TEXT,
    period_start                 TEXT,
    period_end                   TEXT,
    fy_start                     TEXT,
    fy_end                       TEXT,
    board_meeting                TEXT,
    broadcast_ts                 TEXT,
    dissem_ts                    TEXT,
    filing_ts                    TEXT,
    audit_opinion                TEXT,
    n_facts                      INTEGER,
    status                       TEXT,
    parsed_at                    TEXT,
    trading_isin                 TEXT,
    trading_isin_method          TEXT,
    same_issuer                  INTEGER,
    known_at_src                 TEXT,
    known_at_utc                 TEXT,
    known_at_precision           TEXT
);
-- logical mirror of snapshot table results_facts (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.results_facts (
    file                         TEXT,
    concept                      TEXT,
    context                      TEXT,
    period_start                 TEXT,
    period_end                   TEXT,
    instant                      TEXT,
    value                        REAL,
    unit                         TEXT,
    decimals                     TEXT,
    period_kind                  TEXT
);
-- logical mirror of snapshot table ar_docs (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.ar_docs (
    doc_id                       INTEGER,
    isin                         TEXT,
    symbol                       TEXT,
    company                      TEXT,
    fiscal_year                  TEXT,
    fiscal_year_source           TEXT,
    filed_at                     TEXT,
    filed_at_source              TEXT,
    sha256                       TEXT,
    n_pages                      INTEGER,
    n_text_pages                 INTEGER,
    n_pieces                     INTEGER,
    status                       TEXT,
    error                        TEXT,
    ts                           TEXT,
    known_at_src                 TEXT,
    known_at_utc                 TEXT,
    known_at_precision           TEXT
);
-- logical mirror of snapshot table ar_facts (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.ar_facts (
    fact_id                      INTEGER,
    doc_id                       INTEGER,
    piece                        INTEGER,
    isin                         TEXT,
    symbol                       TEXT,
    fiscal_year                  TEXT,
    filed_at                     TEXT,
    page                         INTEGER,
    category                     TEXT,
    item                         TEXT,
    value_raw                    TEXT,
    value                        REAL,
    unit                         TEXT,
    period                       TEXT,
    basis                        TEXT,
    quote                        TEXT,
    model                        TEXT,
    value_check                  TEXT,
    prompt_version               TEXT,
    known_at_src                 TEXT,
    known_at_utc                 TEXT,
    known_at_precision           TEXT
);
-- logical mirror of snapshot table deck_facts (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.deck_facts (
    isin                         TEXT,
    symbol                       TEXT,
    doc_type                     TEXT,
    sha256                       TEXT,
    page_no                      INTEGER,
    prompt_version               TEXT,
    model                        TEXT,
    line_no                      INTEGER,
    metric                       TEXT,
    period                       TEXT,
    raw_number                   TEXT,
    value                        REAL,
    unit                         TEXT,
    is_final                     INTEGER,
    known_at_src                 TEXT,
    known_at_utc                 TEXT,
    known_at_precision           TEXT
);
-- logical mirror of snapshot table deck_pages (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.deck_pages (
    sha256                       TEXT,
    page_no                      INTEGER,
    prompt_version               TEXT,
    doc_id                       TEXT,
    isin                         TEXT,
    symbol                       TEXT,
    doc_type                     TEXT,
    route                        TEXT,
    n_facts                      INTEGER,
    status                       TEXT,
    known_at_src                 TEXT,
    known_at_utc                 TEXT,
    known_at_precision           TEXT
);
-- logical mirror of snapshot table deck_sources (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.deck_sources (
    source                       TEXT,
    source_id                    TEXT,
    symbol                       TEXT,
    isin                         TEXT,
    exch_code                    TEXT,
    known_at                     TEXT,
    title                        TEXT,
    url                          TEXT,
    sha256                       TEXT,
    size_bytes                   INTEGER,
    status                       TEXT,
    error                        TEXT,
    fetched_at                   TEXT,
    known_at_src                 TEXT,
    known_at_utc                 TEXT,
    known_at_precision           TEXT
);
-- logical mirror of snapshot table cc_docs (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.cc_docs (
    doc_id                       INTEGER,
    isin                         TEXT,
    symbol                       TEXT,
    filed_at                     TEXT,
    status                       TEXT,
    model                        TEXT,
    key_name                     TEXT,
    chars                        INTEGER,
    in_tok                       INTEGER,
    out_tok                      INTEGER,
    cost_usd                     REAL,
    seconds                      REAL,
    error                        TEXT,
    run_at                       TEXT,
    priority                     INTEGER,
    period_discussed             TEXT,
    period_q                     INTEGER,
    period_fy                    INTEGER,
    known_at_src                 TEXT,
    known_at_utc                 TEXT,
    known_at_precision           TEXT
);
-- logical mirror of snapshot table cc_items (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.cc_items (
    doc_id                       INTEGER,
    list_name                    TEXT,
    idx                          INTEGER,
    isin                         TEXT,
    filed_at                     TEXT,
    metric                       TEXT,
    value                        TEXT,
    unit                         TEXT,
    period                       TEXT,
    basis                        TEXT,
    direction                    TEXT,
    firmness                     TEXT,
    signal                       TEXT,
    statement                    TEXT,
    quote                        TEXT,
    known_at_src                 TEXT,
    known_at_utc                 TEXT,
    known_at_precision           TEXT
);
-- logical mirror of snapshot table bse_ann (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.bse_ann (
    NEWSID                       TEXT,
    SCRIP_CD                     TEXT,
    ATTACHMENTNAME               TEXT,
    NEWSSUB                      TEXT,
    HEADLINE                     TEXT,
    CATEGORYNAME                 TEXT,
    SUBCATNAME                   TEXT,
    NEWS_DT                      TEXT,
    DT_TM                        TEXT,
    News_submission_dt           TEXT,
    DissemDT                     TEXT,
    QUARTER_ID                   TEXT,
    Fld_Attachsize               TEXT,
    ANNOUNCEMENT_TYPE            TEXT,
    symbol                       TEXT,
    known_at_src                 TEXT,
    known_at_utc                 TEXT,
    known_at_precision           TEXT
);
-- logical mirror of snapshot table fii_dii_cash (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.fii_dii_cash (
    date                         TEXT,
    fii_purchase_cr              REAL,
    fii_sales_cr                 REAL,
    fii_net_cr                   REAL,
    dii_purchase_cr              REAL,
    dii_sales_cr                 REAL,
    dii_net_cr                   REAL,
    nifty_close                  REAL,
    nifty_prev_close             REAL,
    nifty_change_pct             REAL,
    source                       TEXT,
    known_at_src                 TEXT,
    known_at_utc                 TEXT,
    known_at_precision           TEXT
);
-- logical mirror of snapshot table symbol_isin_history (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.symbol_isin_history (
    exchange                     TEXT,
    symbol                       TEXT,
    isin                         TEXT,
    first_date                   TEXT,
    last_date                    TEXT,
    n_days                       INTEGER
);
-- logical mirror of snapshot table security_master (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.security_master (
    isin                         TEXT,
    issuer                       TEXT,
    name                         TEXT,
    nse_symbol                   TEXT,
    bse_code                     TEXT,
    bse_symbol                   TEXT,
    bse_status                   TEXT,
    segment                      TEXT,
    nse_listing_date             TEXT,
    first_trade                  TEXT,
    last_trade                   TEXT,
    last_seen_nse                TEXT,
    last_seen_bse                TEXT,
    in_master_companies          INTEGER,
    source                       TEXT
);
-- logical mirror of snapshot table price_bands (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.price_bands (
    date                         TEXT,
    symbol                       TEXT,
    series                       TEXT,
    band                         TEXT,
    remarks                      TEXT,
    known_at_src                 TEXT,
    known_at_utc                 TEXT,
    known_at_precision           TEXT
);
-- logical mirror of snapshot table pib_releases (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.pib_releases (
    prid                         INTEGER,
    release_date                 TEXT,
    posted_at                    TEXT,
    ministry                     TEXT,
    title                        TEXT,
    relevant                     INTEGER,
    fetched_at                   TEXT,
    doc_id                       INTEGER,
    known_at_src                 TEXT,
    known_at_utc                 TEXT,
    known_at_precision           TEXT
);
-- logical mirror of snapshot table policy_events (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.policy_events (
    id                           INTEGER,
    source_kind                  TEXT,
    source_id                    TEXT,
    section                      INTEGER,
    published_at                 TEXT,
    title                        TEXT,
    policy_name                  TEXT,
    instrument                   TEXT,
    stage                        TEXT,
    direction_for_industry       TEXT,
    sectors                      TEXT,
    companies                    TEXT,
    products                     TEXT,
    amount_inr_crore             REAL,
    old_value                    TEXT,
    new_value                    TEXT,
    unit                         TEXT,
    effective_date               TEXT,
    end_date                     TEXT,
    geography                    TEXT,
    quote                        TEXT,
    quote_ok                     INTEGER,
    model                        TEXT,
    extracted_at                 TEXT,
    known_at_src                 TEXT,
    known_at_utc                 TEXT,
    known_at_precision           TEXT
);
-- logical mirror of snapshot table nse_master (physical: DuckDB; columnar, no indexes)
CREATE TABLE IF NOT EXISTS truth_duckdb.nse_master (
    symbol                       TEXT,
    isin                         TEXT,
    name                         TEXT,
    segment                      TEXT
);


-- snapshot tables not declared here (same DDL as their live source): nse_master,
-- px_daily/px_nse/px_bse/px_bse_adj/px_nse_adj, results_*, ar_*, deck_*, cc_*, bse_ann,
-- fii_dii_cash, symbol_isin_history, security_master, price_bands, pib_releases,
-- policy_events, events.


-- =====================================================================================
-- 3. market_state.db - layer-2 daily state + intervals, layer-3 macro claims,
--    layer-4 external dated series. One writer: the T1/macro build jobs.
-- =====================================================================================

-- [table] market_state.build_run
CREATE TABLE IF NOT EXISTS market_state.build_run (
    run_id     TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    doc_type   TEXT,
    docs_in    INTEGER, docs_ok INTEGER, docs_failed INTEGER,
    chunks_out INTEGER, tags_out INTEGER, notes TEXT
);

-- [table] market_state.company_state_daily
-- =====================================================================================
-- §B  market_state.db — layer-2 market state (daily), layer-3 macro claims, events.
-- =====================================================================================

-- LAYER 2, daily part. One row per ISIN per session.
-- BUILD: 6,940 master ISINs x 1,936 sessions (2019-01-01..2026-10-23) <= 13.4M rows;
-- measured source px_daily 7.3M rows + mkt_nse_full_daily 4.3M + mkt_bse_eq_daily 7.5M.
-- 15 min (join + shares_out merge + bucket compute).
CREATE TABLE IF NOT EXISTS market_state.company_state_daily (
    isin            TEXT NOT NULL,
    date            TEXT NOT NULL,          -- trading session, YYYY-MM-DD
    close           REAL,
        -- SOURCE: px_daily.adj_close (7.3M rows, 100% adj) / daily_price_delivery.close
    mcap_cr         REAL,
        -- SOURCE: close x shares_out / 1e7; shares from results_xbrl paid-up / face value
        --         cross-checked against shp_index (50,838 rows, 100% promoter fill)
    shares_out      INTEGER,
        -- SOURCE: results_xbrl.facts concept PaidUpValueOfEquityShareCapital /
        --         FaceValueOfEquityShareCapital (554 distinct concepts, 13.9M facts),
        --         annual-report shareholding totals (ar_facts, category='shareholding'),
        --         or a split/bonus-adjusted backcast (corporate_actions) before FY23.
    shares_source   TEXT,                   -- xbrl_paidup|ar_shareholding|action_adjusted
    pit_conf        REAL,
        -- 1.0 = filed fact known by the session; 0.9 = filed fact + split/bonus
        -- adjustment; 0.6 = backcast from a later fact (fills pre-FY23 only).
    mcap_bucket     TEXT CHECK (mcap_bucket IN ('LARGE','MID','SMALL','MICRO')),
        -- SOURCE: computed (SEBI size rule) from mcap_cr; intervals are a view below
    price_band      INTEGER,                -- 2|5|10|20|40; NULL = no band
        -- SOURCE: price_bands.band (1,054,354 rows, 2019-12-30..2026-09-22, 100% fill)
        --         + raw D:/RealityEngine/raw/price_bands for the missing windows
    is_fno          INTEGER NOT NULL DEFAULT 0,
        -- SOURCE: master_companies.is_fno_eligible snapshot + NSE F&O ban list history
    traded_value_20d_cr REAL,
        -- SOURCE: px_daily.value_inr 20-session rolling sum
    known_at        TEXT NOT NULL,          -- session close, 15:30 IST
    PRIMARY KEY (isin, date)
) WITHOUT ROWID;

-- [table] market_state.isin_rekey_map
-- serves: "band on results day", "did the band change before the announcement" (MB0416);
-- a PK lookup on company_state_daily(isin, date) — no extra index needed.

-- ISIN-history repair ledger (G0: 83 false changes, 1,370 synthetic ISINs, 1,665 FY25+
-- ISINs absent from master). One row per accepted re-key; the resolver consults it before
-- symbol_isin_history so a split/face-value ISIN change cannot rewrite history.
-- SOURCE: px_bse.sc_code/isin, security_master (8,434 rows), symbol_isin_history (9,360),
-- corporate_actions (18,240), isin_rekey_log (held, write-ahead log of past rekeys).
-- BUILD: ~2,000 rows; 2 days curation (G0 effort 2.0 d), 1 min to write.
CREATE TABLE IF NOT EXISTS market_state.isin_rekey_map (
    old_isin    TEXT NOT NULL,
    new_isin    TEXT NOT NULL,
    effective_on TEXT NOT NULL,
    reason      TEXT NOT NULL,      -- split|face_value|merger|demerger|symbol_change|synthetic
    verified    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (old_isin, new_isin)
) WITHOUT ROWID;

-- [table] market_state.index_list
-- One row per Nifty index named in the 446 dated constituent-change notices.
-- coverage='snapshot'  : full constituent list held (index_membership / current_*.csv);
-- coverage='derived'   : snapshot derived from held lists (Next 50, LargeMidcap 250,
--                        MidSmallcap 400) -- exact by index definition;
-- coverage='changes_only': no snapshot anywhere, only the dated changes are known, so
--                        the intervals are partial and pit_conf < 1.
CREATE TABLE IF NOT EXISTS market_state.index_list (
    index_code      TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    broad_or_sector TEXT NOT NULL CHECK (broad_or_sector IN ('broad','sector','thematic')),
    size            INTEGER,
    history_from    TEXT,
    coverage        TEXT,
    snapshot_date   TEXT,
    members_at_snapshot INTEGER,
    changes_parsed  INTEGER,
    pit_conf        REAL
);

-- [table] market_state.company_membership_pit
-- Interval table: piecewise constant. One seek answers "was X in Midcap 150 on D".
-- SOURCE: NSE index circulars (new fetch) + index_membership snapshot (300 rows,
-- as_of 2026-09-30) + master_companies.is_nifty50/100/200/500 flags backcast.
-- BUILD: ~8k rows after the circular backfill; 3 min.
CREATE TABLE IF NOT EXISTS market_state.company_membership_pit (
    isin        TEXT NOT NULL,
    index_code  TEXT NOT NULL REFERENCES index_list(index_code),
    added_on    TEXT NOT NULL,
    removed_on  TEXT,
    source      TEXT NOT NULL,      -- nse_notice|snapshot_backcast|manual
    pit_conf    REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (isin, index_code, added_on)
) WITHOUT ROWID;

-- [table] market_state.company_sector_pit
-- SOURCE: company_industry (2,055 rows, current) + master_companies.industry (4,231) +
-- BSE scrip-master history (new fetch). GC4 gap: current snapshot only otherwise.
-- BUILD: 6,940 x ~2 classifications = 14k rows; 5 min.
CREATE TABLE IF NOT EXISTS market_state.company_sector_pit (
    isin           TEXT NOT NULL,
    macro          TEXT,
    sector         TEXT,
    industry       TEXT,
    basic_industry TEXT,
    valid_from     TEXT NOT NULL,
    valid_to       TEXT,
    source         TEXT NOT NULL,   -- nse_classification|bse_classification|manual
    PRIMARY KEY (isin, valid_from)
) WITHOUT ROWID;

-- [table] market_state.company_theme_pit
-- SOURCE: curated theme_map matches (basic_industry/sector/keyword/isin) applied to
-- company_sector_pit + company_business_features. No model needed.
-- BUILD: 20 themes x ~40 members = 800 rows; 20 min curation, 1 min to write.
CREATE TABLE IF NOT EXISTS market_state.company_theme_pit (
    isin       TEXT NOT NULL,
    theme      TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to   TEXT,
    source     TEXT NOT NULL,       -- curated_map|opinion_theme
    confidence REAL,
    PRIMARY KEY (isin, theme, valid_from)
) WITHOUT ROWID;

-- [table] market_state.theme_map
CREATE TABLE IF NOT EXISTS market_state.theme_map (
    theme       TEXT NOT NULL,
    match_kind  TEXT NOT NULL CHECK (match_kind IN ('basic_industry','sector','keyword','isin')),
    match_value TEXT NOT NULL,
    weight      REAL NOT NULL DEFAULT 1.0,
    source      TEXT NOT NULL,
    PRIMARY KEY (theme, match_kind, match_value)
) WITHOUT ROWID;

-- [table] market_state.company_ownership_pit
-- SOURCE: shp_index (50,838 rows, isin 49,203, broadcast_at 100%, promoter_pct 100%,
-- public_pct 100%) + shp_facts (30,509 raw XBRL facts) for pledge/encumbrance cells.
-- This table is why NG05 ("shareholding is a 40-row stub") is closed: the view is the
-- stub, shp_index is the live PIT store. BUILD: 50,838 rows; 2 min.
CREATE TABLE IF NOT EXISTS market_state.company_ownership_pit (
    isin         TEXT NOT NULL,
    quarter_end  TEXT NOT NULL,
    known_at     TEXT NOT NULL,     -- shp_index.broadcast_at (exchange broadcast)
    promoter_pct REAL,
    pledge_pct   REAL,
    fii_pct      REAL,
    dii_pct      REAL,
    mf_pct       REAL,
    public_pct   REAL,
    source       TEXT NOT NULL,     -- shp_index|shp_facts|shareholding_xbrl
    PRIMARY KEY (isin, quarter_end)
) WITHOUT ROWID;

-- [table] market_state.event_day0
-- LAYER 2, events. The 15:30 rule: a filing after 15:30 belongs to the next session.
-- SOURCE: known_at from every store (truth_duckdb.events 3.3M rows is the spine) mapped
-- to the NSE trading calendar. BUILD: 3.3M events -> 3.3M rows; 6 min.
CREATE TABLE IF NOT EXISTS market_state.event_day0 (
    event_id    TEXT NOT NULL,
    isin        TEXT NOT NULL,
    event_kind  TEXT NOT NULL,      -- results|announcement|concall|deck|board|deal|insider|sast
    known_at    TEXT NOT NULL,
    session_0   TEXT NOT NULL,      -- first session that could trade on the news
    offset      INTEGER NOT NULL,   -- 0 = same session, 1 = next session
    in_session  INTEGER NOT NULL,   -- 1 if known_at before 15:30 IST
    pit_conf    REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (event_id, isin)
) WITHOUT ROWID;

-- [table] market_state.event_leakage_window
-- The pre-event window: 10 sessions before day0 to 10 after, normalised.
-- SOURCE: px_daily + daily_price_delivery + insider_trades_v2 (333,712 rows) +
-- bulk_block_deals (271,800). Restrict to material events (~300k) or the table is 69M rows.
-- BUILD: 300k events x 21 offsets = 6.3M rows; 25 min.
CREATE TABLE IF NOT EXISTS market_state.event_leakage_window (
    event_id    TEXT NOT NULL,
    isin        TEXT NOT NULL,
    offset      INTEGER NOT NULL,   -- -10..+10 sessions from day0
    date        TEXT NOT NULL,
    ret_pct     REAL,
        -- SOURCE: px_daily.adj_close pct change / own 60-session vol (volatility normaliser)
    delivery_z  REAL,
        -- SOURCE: daily_price_delivery.delivery_pct z-score vs own 60-session mean
    insider_net_inr REAL,
        -- SOURCE: insider_trades_v2 qty x value_inr in the window
    deal_net_inr REAL,
        -- SOURCE: bulk_block_deals + mkt_nse_deals + mkt_bse_deals in the window
    known_at    TEXT NOT NULL,      -- = event_day0.known_at (window is only knowable then)
    PRIMARY KEY (event_id, isin, offset)
) WITHOUT ROWID;

-- [table] market_state.macro_doc
-- LAYER 3. One row per macro document. SOURCE: raw_documents (39,645) filtered to
-- PIB 75,361 live pib_releases rows, budgets, RBI, Economic Survey + policy_events
-- (21,552 rows, published_at 100%, quote_ok 20,970, companies 21,552, sectors 21,552).
-- BUILD: 80k macro docs; 8 min (no reader).
CREATE TABLE IF NOT EXISTS market_state.macro_doc (
    doc_id    TEXT PRIMARY KEY,     -- same id space as chunks_v3.doc.doc_id
    source    TEXT NOT NULL,        -- PIB_Press_Release|Union_Budget|State_Budget|RBI|Survey|News
    doc_type  TEXT NOT NULL CHECK (doc_type IN
              ('pib','union_budget','state_budget','rbi_policy','rbi_report','economic_survey','news')),
    issuer    TEXT,                 -- ministry / state / RBI department
    title     TEXT,
    event_date TEXT,
    known_at  TEXT NOT NULL,
    pit_conf  REAL NOT NULL DEFAULT 1.0,
    language  TEXT DEFAULT 'en'
);

-- [table] market_state.macro_claim_target
-- Which sectors / industries / themes / companies a claim touches. This is G10/policy_target.
-- SOURCE: macro_claim + company_sector_pit + curated sector aliases ('Textiles & Apparel'
-- maps to basic_industry). BUILD: ~3 targets/claim = 180k rows; 15 min after the claim pass.
CREATE TABLE IF NOT EXISTS market_state.macro_claim_target (
    claim_id    INTEGER NOT NULL,
    target_kind TEXT NOT NULL CHECK (target_kind IN
                ('sector','basic_industry','theme','isin','commodity','state')),
    target_id   TEXT NOT NULL,
    direction   TEXT NOT NULL CHECK (direction IN ('positive','negative','neutral')),
    weight      REAL NOT NULL DEFAULT 1.0,
    evidence    TEXT,
    PRIMARY KEY (claim_id, target_kind, target_id),
    FOREIGN KEY (claim_id) REFERENCES macro_claim(claim_id) ON DELETE CASCADE
) WITHOUT ROWID;

-- [table] market_state.event_calendar
-- serves: R01-R10 cases that name `policy_target` directly

-- Macro-event calendar: elections, verdicts, geopolitical shocks, RBI/budget dates.
-- SOURCE: policy_events (21,552) + macro_events (30 rows, 24 with doc_id) + curated
-- external record. BUILD: ~2k rows; 2 h curation, 1 min to write.
CREATE TABLE IF NOT EXISTS market_state.event_calendar (
    event_id   TEXT PRIMARY KEY,
    event_kind TEXT NOT NULL,       -- rbi|budget|election|verdict|geopolitical|commodity_shock
    event_date TEXT NOT NULL,
    scope      TEXT,                -- india|us|eu|global|state:XX
    title      TEXT,
    doc_id     TEXT,
    known_at   TEXT NOT NULL,
    pit_conf   REAL NOT NULL DEFAULT 1.0
);

-- [table] market_state.sector_flow_daily
-- Sector-level FII/DII attribution derived from the deal tape (NG18).
-- SOURCE: mkt_fii_dii_cash (1,935 rows, market-wide) + bulk_block_deals (271,800) +
-- mkt_nsdl_fpi_daily (30,128) joined to company_sector_pit. Label derived, not official.
-- BUILD: 1,936 sessions x ~20 sectors = 39k rows; 15 min.
CREATE TABLE IF NOT EXISTS market_state.sector_flow_daily (
    date        TEXT NOT NULL,
    sector      TEXT NOT NULL,
    fii_net_cr  REAL,               -- derived: marquee-institution legs in bulk/block deals
    dii_net_cr  REAL,
    method      TEXT NOT NULL,      -- deal_tape_v1
    PRIMARY KEY (date, sector)
) WITHOUT ROWID;

-- [table] market_state.fno_oi_daily
-- F&O open interest, PCR and max-pain inputs (reddit ta_oi_buildup / ta_pcr_maxpain).
-- SOURCE: NSE F&O bhavcopy (free daily files, not held -> needs_new_fetch). Per-contract.
-- BUILD: 1,936 sessions x ~2.5k contracts = 4.8M rows; 25 min after fetch.
CREATE TABLE IF NOT EXISTS market_state.fno_oi_daily (
    date        TEXT NOT NULL,
    underlying  TEXT NOT NULL,
    expiry      TEXT NOT NULL,
    strike      REAL,
    option_type TEXT CHECK (option_type IN ('CE','PE','FUT')),
    oi          REAL, oi_change REAL, volume REAL, settle REAL,
    isin        TEXT,
    PRIMARY KEY (date, underlying, expiry, strike, option_type)
) WITHOUT ROWID;

-- [table] market_state.ipo_grey_market
-- IPO grey-market premium and listing-day context (reddit ipo_grey_listing).
-- SOURCE: unofficial grey-market quotes (no official source; pit_conf 0.5) + px_daily for
-- the listing day. BUILD: ~1.1k listings x 5 days = 5.5k rows; 30 min curation.
CREATE TABLE IF NOT EXISTS market_state.ipo_grey_market (
    isin       TEXT NOT NULL,
    date       TEXT NOT NULL,
    phase      TEXT NOT NULL CHECK (phase IN ('open','close','listing_eve')),
    gmp_inr    REAL,
    issue_price REAL,
    source     TEXT NOT NULL,       -- unofficial: ipo_watch|investorgain
    pit_conf   REAL NOT NULL DEFAULT 0.5,
    PRIMARY KEY (isin, date, phase)
) WITHOUT ROWID;

-- [table] market_state.corporate_action_class
-- Ordinary vs special dividend/buyback classification (NG23, 2 cases).
-- SOURCE: corporate_actions (18,240 rows, action_type 100%, ex_date 100%) + announcement
-- text. BUILD: 18k rows; 10 min deterministic + 20 min reader spot-check.
CREATE TABLE IF NOT EXISTS market_state.corporate_action_class (
    isin        TEXT NOT NULL,
    ex_date     TEXT NOT NULL,
    action_type TEXT NOT NULL,
    ordinary    INTEGER,            -- 1 ordinary, 0 special/one-off, NULL unknown
    amount_per_share REAL,
    known_at    TEXT NOT NULL,      -- corporate_actions.broadcast_date
    PRIMARY KEY (isin, ex_date, action_type)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS market_state.ix_csd_date_bucket ON company_state_daily(date, mcap_bucket);

CREATE INDEX IF NOT EXISTS market_state.ix_csd_date_band ON company_state_daily(date, price_band);

CREATE INDEX IF NOT EXISTS market_state.ix_csd_date_fno ON company_state_daily(date, is_fno);

CREATE INDEX IF NOT EXISTS market_state.ix_irm_effective ON isin_rekey_map(effective_on);

CREATE INDEX IF NOT EXISTS market_state.ix_cmp_index_added ON company_membership_pit(index_code, added_on);

CREATE INDEX IF NOT EXISTS market_state.ix_cmp_index_removed ON company_membership_pit(index_code, removed_on);

CREATE INDEX IF NOT EXISTS market_state.ix_csp_basic ON company_sector_pit(basic_industry, valid_from);

CREATE INDEX IF NOT EXISTS market_state.ix_csp_sector ON company_sector_pit(sector, valid_from);

CREATE INDEX IF NOT EXISTS market_state.ix_ctp_theme ON company_theme_pit(theme, valid_from);

CREATE INDEX IF NOT EXISTS market_state.ix_cop_known ON company_ownership_pit(known_at);

CREATE INDEX IF NOT EXISTS market_state.ix_ed0_isin_sess ON event_day0(isin, session_0);

CREATE INDEX IF NOT EXISTS market_state.ix_ed0_sess ON event_day0(session_0, event_kind);

CREATE INDEX IF NOT EXISTS market_state.ix_elw_isin_date ON event_leakage_window(isin, date);

CREATE INDEX IF NOT EXISTS market_state.ix_mct_target ON macro_claim_target(target_kind, target_id);

CREATE INDEX IF NOT EXISTS market_state.ix_ec_date ON event_calendar(event_date, event_kind);

CREATE INDEX IF NOT EXISTS market_state.ix_fno_isin_date ON fno_oi_daily(isin, date);

CREATE INDEX IF NOT EXISTS market_state.ix_cac_date ON corporate_action_class(ex_date, action_type);

-- One row per extracted claim. BUILT (21,552 rows, macro_all.db) from policy_events;
-- the six pilot columns (paraphrase, known_at, stratum, conditions, quote_ok,
-- effective_pit_conf) are part of the table because the RIPPLE trigger uses them.
CREATE TABLE IF NOT EXISTS market_state.macro_claim (
    claim_id            INTEGER PRIMARY KEY,
    doc_id              TEXT NOT NULL,
    clause_no           TEXT,
    policy_type         TEXT NOT NULL,
    instrument          TEXT,
    direction           TEXT NOT NULL CHECK (direction IN ('positive','negative','neutral','mixed')),
    magnitude_value     REAL,
    magnitude_unit      TEXT,
    magnitude_raw       TEXT,
    effective_date      TEXT,
    end_date            TEXT,
    quote               TEXT NOT NULL,
    char_start          INTEGER,
    char_end            INTEGER,
    model               TEXT NOT NULL,
    confidence          REAL,
    verified            INTEGER NOT NULL DEFAULT 0,
    paraphrase          TEXT,
    known_at            TEXT,
    stratum             TEXT,
    conditions          TEXT,
    quote_ok            INTEGER,
    effective_pit_conf  REAL,
    FOREIGN KEY (doc_id) REFERENCES macro_doc(doc_id)
);
CREATE INDEX IF NOT EXISTS market_state.ix_mclaim_doc ON macro_claim(doc_id);
CREATE INDEX IF NOT EXISTS market_state.ix_mclaim_type ON macro_claim(policy_type, effective_date);
CREATE INDEX IF NOT EXISTS market_state.ix_mclaim_known ON macro_claim(known_at);

-- [view] market_state.mcap_bucket_interval
-- Market-cap bucket as an interval: one row per (isin, bucket) stint.
-- SOURCE: derived from company_state_daily (bucket change detection, 13.4M -> ~14k rows).
CREATE VIEW IF NOT EXISTS market_state.mcap_bucket_interval AS
SELECT isin,
       mcap_bucket,
       MIN(date) AS valid_from,
       CASE WHEN MAX(date) = (SELECT MAX(date) FROM company_state_daily)
            THEN NULL ELSE MAX(date) END AS valid_to
FROM company_state_daily
GROUP BY isin, mcap_bucket;

-- [view] market_state.price_band_daily
-- serves: "was X a large cap on 2023-06-30" with one range scan; no extra table because
-- the daily rows already answer it and a second copy would be 13.4M duplicated values.

-- Price band as a nameable table (the task and MB0416 ask for it). A view, not a copy:
-- the band is a column on the daily row, so a second 13.4M-row table would only duplicate.
-- SOURCE: price_bands.band (1,054,354 rows, 100% fill, 2019-12-30..2026-09-22) +
-- raw D:/RealityEngine/raw/price_bands + circuit_hits (243,049 rows) for band-lock days,
-- resolved to ISIN and written into company_state_daily.price_band at build time.
CREATE VIEW IF NOT EXISTS market_state.price_band_daily AS
SELECT isin, date, price_band AS band,
       CASE WHEN price_band IS NULL THEN 0 ELSE 1 END AS has_band
FROM company_state_daily;

-- [view] market_state.policy_target
-- Compatibility view: the ripple bank calls this table policy_target.
CREATE VIEW IF NOT EXISTS market_state.policy_target AS
SELECT claim_id, target_kind, target_id, direction, weight, evidence FROM macro_claim_target;

-- ---------------------------------------------------------------------------------
-- External dated series (merged SCHEMA_V3 macro_series.db into market_state).
-- One physical table for commodity / freight / rain / wage / transit / rate series;
-- the six nameable tables the bank and CASE_MAP use are views over it, so a new
-- series is a row, never a table. series_code is '<kind>:<series>'.
-- ---------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_state.series_meta (
    series_code TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('commodity','freight','rain','wage','transit','rate')),
    source      TEXT NOT NULL,
    unit        TEXT NOT NULL,
    cadence     TEXT NOT NULL CHECK (cadence IN ('daily','weekly','monthly')),
    fetched_to  TEXT,
    pit_note    TEXT
);
CREATE TABLE IF NOT EXISTS market_state.series_observation (
    series_code  TEXT NOT NULL REFERENCES series_meta(series_code),
    dim_id       TEXT NOT NULL,          -- district | state | route | commodity code
    kind         TEXT NOT NULL CHECK (kind IN ('commodity','freight','rain','wage','transit','rate')),
    period_start TEXT NOT NULL,          -- observation date, or first day of month
    period_end   TEXT,
    value        REAL NOT NULL,
    unit         TEXT NOT NULL,
    departure_pct REAL,                  -- rainfall only
    source       TEXT NOT NULL,
    known_at     TEXT NOT NULL,          -- release timestamp, never the period end
    pit_conf     REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (series_code, period_start)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS market_state.ix_so_kind_date ON series_observation(kind, period_start);
CREATE VIEW IF NOT EXISTS market_state.commodity_price_daily AS
SELECT series_code, dim_id AS commodity, period_start AS date, value AS close, unit, known_at, pit_conf
FROM market_state.series_observation WHERE kind = 'commodity';
CREATE VIEW IF NOT EXISTS market_state.freight_rate_daily AS
SELECT series_code, dim_id AS route_code, period_start AS date, value AS rate_usd, unit, known_at
FROM market_state.series_observation WHERE kind = 'freight';
CREATE VIEW IF NOT EXISTS market_state.rainfall_daily AS
SELECT series_code, dim_id AS region, period_start AS date, value AS rain_mm,
       departure_pct, known_at
FROM market_state.series_observation WHERE kind = 'rain';
CREATE VIEW IF NOT EXISTS market_state.rural_wage_series AS
SELECT series_code, dim_id AS state, period_start AS month, value AS wage_inr, known_at
FROM market_state.series_observation WHERE kind = 'wage';
CREATE VIEW IF NOT EXISTS market_state.shipment_transit AS
SELECT series_code, dim_id AS route_code, period_start AS date, value AS transit_days, known_at
FROM market_state.series_observation WHERE kind = 'transit';
CREATE VIEW IF NOT EXISTS market_state.rate_series_daily AS
SELECT series_code, period_start AS date, value AS value_pct, known_at, pit_conf
FROM market_state.series_observation WHERE kind = 'rate';


-- =====================================================================================
-- 4. metric_state.db - the structured-number layer. Inputs are held; the build is
--    parsing/mapping, not fetching. Reader-filled tables say so in the DDL comment.
-- =====================================================================================

-- [table] metric_state.build_run
CREATE TABLE IF NOT EXISTS metric_state.build_run (
    run_id     TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    doc_type   TEXT,
    docs_in    INTEGER, docs_ok INTEGER, docs_failed INTEGER,
    chunks_out INTEGER, tags_out INTEGER, notes TEXT
);

-- [table] metric_state.xbrl_concept_map
-- =====================================================================================
-- §C  metric_state.db — the structured-number layer. Every table here is a VIEW over
-- held facts in the sense that its inputs are held; the build is parsing/mapping, not
-- fetching. Reader-filled tables say so and carry the reader cost.
-- =====================================================================================

-- The concept map that unlocks G11: one row per (taxonomy, concept, metric_key, sign).
-- SOURCE: results_xbrl.facts has 554 distinct concepts (measured) across 4 taxonomies;
-- hand-map the 60 metrics the bank needs, leave the rest unmapped.
-- BUILD: 60 metrics x ~4 taxonomies = 240 rows; 1 day curation (G11 effort: 1.0 d).
CREATE TABLE IF NOT EXISTS metric_state.xbrl_concept_map (
    taxonomy     TEXT NOT NULL,     -- INDAS|INTEGRATED|NBFC|NONINDAS
    concept      TEXT NOT NULL,
    metric_key   TEXT NOT NULL,     -- revenue|ebitda|pat|net_worth|borrowings|npa_gnpa|...
    unit_scale   REAL NOT NULL DEFAULT 1.0,   -- XBRL rupees -> crore = 1e-7
    sign         INTEGER NOT NULL DEFAULT 1,
    basis_default TEXT,             -- standalone|consolidated
    verified     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (taxonomy, concept)
) WITHOUT ROWID;

-- [table] metric_state.company_metric_series
-- The full quarterly series the bank asks for (62 cases). Long format so new metrics
-- need no migration. SOURCE: results_xbrl.facts (13,941,210 rows) x xbrl_concept_map,
-- plus 5,000-odd results-note numbers where XBRL is silent.
-- BUILD: 45,517 FY25+ filings x ~20 mapped metrics = 910k rows; 20 min.
CREATE TABLE IF NOT EXISTS metric_state.company_metric_series (
    isin        TEXT NOT NULL,
    metric_key  TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    period_kind TEXT NOT NULL CHECK (period_kind IN ('quarter','half','fy','instant')),
    basis       TEXT NOT NULL CHECK (basis IN ('standalone','consolidated')),
    value       REAL NOT NULL,
    unit        TEXT NOT NULL DEFAULT 'INR_CRORE',
    source      TEXT NOT NULL,      -- xbrl|results_notes|ar|deck
    doc_id      TEXT,
    known_at    TEXT NOT NULL,      -- filings.dissem_ts (95% fill)
    pit_conf    REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (isin, metric_key, period_end, period_kind, basis)
) WITHOUT ROWID;

-- [table] metric_state.company_result_pit
-- SOURCE: results_xbrl.filings (106,613 rows; taxonomy INDAS 69,520, INTEGRATED 30,227,
-- NBFC 3,903, NONINDAS 1,576; broadcast_ts 96%, dissem_ts 95%) x xbrl_concept_map.
-- BUILD: 45,517 FY25+ filings x ~8 headline metrics = 364k rows; 10 min.
CREATE TABLE IF NOT EXISTS metric_state.company_result_pit (
    isin         TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    basis        TEXT NOT NULL CHECK (basis IN ('standalone','consolidated')),
    known_at     TEXT NOT NULL,     -- filings.dissem_ts (not period end)
    revenue_cr   REAL, ebitda_cr REAL, pat_cr REAL, ebitda_margin REAL,
    revenue_yoy  REAL, pat_yoy REAL, eps REAL,
    source       TEXT NOT NULL,     -- xbrl|annual_report|deck
    PRIMARY KEY (isin, period_end, basis)
) WITHOUT ROWID;

-- [table] metric_state.company_segment_pnl
-- Segment P&L (41 cases + 50 ripple hops). SOURCE: ar_facts category='segment'
-- (145,742 facts, 4,217 ISINs, segment name embedded in item, quote+page held) +
-- deck_figures.facts metric 'Segment Revenue' (1,986 rows, 46 ISINs) + XBRL
-- SegmentRevenue (64,033 facts / 36,294 files) ONLY where the context member is
-- recovered by re-parsing the XBRL context (today results_xbrl.facts context='OneD',
-- i.e. the member is lost — that is the real reason this gap exists).
-- BUILD: 145k parsed facts -> ~35k segment rows; 45 min deterministic + 2 h validation.
CREATE TABLE IF NOT EXISTS metric_state.company_segment_pnl (
    isin         TEXT NOT NULL,
    segment      TEXT NOT NULL,     -- normalized name ('Automotive', 'JLR', 'Others')
    period_end   TEXT NOT NULL,
    metric       TEXT NOT NULL,     -- revenue|ebit|ebitda|segment_assets|segment_liabilities|capex
    basis        TEXT NOT NULL CHECK (basis IN ('standalone','consolidated')),
    value_cr     REAL NOT NULL,
    share_of_total_pct REAL,
    source       TEXT NOT NULL,     -- ar_segment_note|deck|segment_xbrl
    doc_id       TEXT, page INTEGER,
    known_at     TEXT NOT NULL,     -- ar_docs.filed_at / deck_sources.known_at
    pit_conf     REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (isin, segment, period_end, metric, basis)
) WITHOUT ROWID;

-- [table] metric_state.company_working_capital
-- Working-capital days (25 cases). Computed, never copied (annual_financials has no days).
-- SOURCE: XBRL TradeReceivables/Inventories/TradePayables + Revenue/COGS via concept map;
-- AR receivables_ageing (132,937 facts) for the ageing split.
-- BUILD: 6,940 ISINs x 8 years = 55k rows; 15 min.
CREATE TABLE IF NOT EXISTS metric_state.company_working_capital (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    basis       TEXT NOT NULL CHECK (basis IN ('standalone','consolidated')),
    receivables_cr REAL, inventory_cr REAL, payables_cr REAL, revenue_cr REAL, cogs_cr REAL,
    dso REAL, dio REAL, dpo REAL, ccc REAL,
    source      TEXT NOT NULL,      -- xbrl|ar_schedule
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, basis)
) WITHOUT ROWID;

-- [table] metric_state.company_interest_cover
-- Interest cover computed from EBIT and finance cost (2 cases + the solvency gate).
-- SOURCE: XBRL FinanceCosts/ProfitBeforeTax; measured reason for the table:
-- annual_financials.interest_coverage has 0 rows < 2.5x in 3,245 FY26 rows, so it cannot
-- rank solvency. BUILD: 55k rows; 10 min.
CREATE TABLE IF NOT EXISTS metric_state.company_interest_cover (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    basis       TEXT NOT NULL,
    ebit_cr     REAL, finance_cost_cr REAL, cover_x REAL,
    source      TEXT NOT NULL,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, basis)
) WITHOUT ROWID;

-- [table] metric_state.company_debt_mix
-- Borrowing repricing mix (20 cases). SOURCE: AR borrowings_maturity (94,733 facts) +
-- borrowings (618,365 facts) + rating rationale text.
-- BUILD: 55k rows; 25 min deterministic + 3 h reader.
CREATE TABLE IF NOT EXISTS metric_state.company_debt_mix (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    bucket      TEXT NOT NULL,      -- (<1y, 1-3y, 3-5y, >5y) x (fixed, floating)
    amount_cr   REAL,
    rate_pct    REAL,
    repricing_months INTEGER,
    source      TEXT NOT NULL,      -- ar_borrowing_schedule|rating_rationale|deck
    doc_id      TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, bucket)
) WITHOUT ROWID;

-- [table] metric_state.company_price_revision
-- Dated price-hike statements (33 cases). One row per (company, product, announcement).
-- SOURCE: concall_facts.cc_items list_name='pricing_and_competition' (5,003 rows) and
-- 'margin_and_cost_commentary' (7,465), deck text, AR MD&A. Reader-filled.
-- BUILD: ~15k statements; reader 3 h at 8 workers.
CREATE TABLE IF NOT EXISTS metric_state.company_price_revision (
    isin         TEXT NOT NULL,
    announced_on TEXT NOT NULL,
    effective_on TEXT,
    product      TEXT,
    direction    TEXT NOT NULL CHECK (direction IN ('hike','cut','mixed')),
    revision_pct REAL,
    basis_text   TEXT,
    source_doc_id TEXT NOT NULL,
    quote        TEXT NOT NULL,
    known_at     TEXT NOT NULL,     -- the call/filing timestamp, never the quarter end
    pit_conf     REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (isin, announced_on, product, source_doc_id)
) WITHOUT ROWID;

-- [table] metric_state.company_cost_structure
-- Input cost share of COGS (26 cases, R01 chain). SOURCE: ar_facts raw-material
-- consumption note + segment note; share computed against COGS from XBRL.
-- BUILD: 6,940 x 8 years x ~4 inputs = 220k rows; 30 min deterministic + 3 h reader.
CREATE TABLE IF NOT EXISTS metric_state.company_cost_structure (
    isin         TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    basis        TEXT NOT NULL,
    input_key    TEXT NOT NULL,     -- copper|aluminium|steel|coking_coal|crude|power|freight|labour
    amount_cr    REAL,
    share_of_cogs_pct REAL,
    source_doc_id TEXT,
    known_at     TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, basis, input_key)
) WITHOUT ROWID;

-- [table] metric_state.company_import_content
-- Imported raw material share (11 cases) and FX exposure (9 cases).
-- SOURCE: AR "imported vs indigenous" note (ar_facts), FX hedging note, concall comments.
-- BUILD: 55k rows each; 20 min deterministic + 3 h reader.
CREATE TABLE IF NOT EXISTS metric_state.company_import_content (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    imported_raw_material_cr REAL,
    imported_share_pct REAL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end)
) WITHOUT ROWID;

-- [table] metric_state.company_fx_exposure
CREATE TABLE IF NOT EXISTS metric_state.company_fx_exposure (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    usd_revenue_share_pct REAL,
    import_cost_share_pct REAL,
    hedge_cover_pct REAL,
    net_exposure_pct REAL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end)
) WITHOUT ROWID;

-- [table] metric_state.company_revenue_geography
-- Cost geography (3 cases) and revenue geography (6 cases + 20 profile cases).
-- SOURCE: segment note (geographical) in ar_facts/company_segment_pnl for revenue;
-- manufacturing location note for cost. geographic_exposure (3,568 rows, undated) is
-- company_id-keyed and cannot answer "as of FY25" — this table can.
-- BUILD: 6,940 x 8 x 3 = 165k rows revenue; 45k rows cost; 40 min.
CREATE TABLE IF NOT EXISTS metric_state.company_revenue_geography (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    country     TEXT NOT NULL,      -- india|us|europe|row (normalized)
    revenue_share_pct REAL,
    revenue_cr  REAL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, country)
) WITHOUT ROWID;

-- [table] metric_state.company_cost_geography
CREATE TABLE IF NOT EXISTS metric_state.company_cost_geography (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    location    TEXT NOT NULL,
    cost_share_pct REAL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, location)
) WITHOUT ROWID;

-- [table] metric_state.company_capacity_utilisation
-- Capacity, utilisation and capex projects (55 cases). SOURCE: AR capacity note
-- (ar_facts category='capacity', 129,348 facts / 2,945 ISINs), deck_figures 'Capacity'
-- (4,035 rows / 397 ISINs), concall 'capacity_and_projects' (7,281 items).
-- Reader-filled, but the statement is kept DATED because the slip is the answer (A01).
-- BUILD: ~60k statements; reader 6 h at 8 workers.
CREATE TABLE IF NOT EXISTS metric_state.company_capacity_utilisation (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    product     TEXT NOT NULL,
    capacity    REAL,
    capacity_unit TEXT,
    utilisation_pct REAL,
    production  REAL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, product)
) WITHOUT ROWID;

-- [table] metric_state.capex_project
CREATE TABLE IF NOT EXISTS metric_state.capex_project (
    isin        TEXT NOT NULL,
    project     TEXT NOT NULL,
    announced_on TEXT NOT NULL,
    target_on   TEXT,               -- stated commissioning window at announcement
    commissioned_on TEXT,           -- actual, when stated
    capex_cr    REAL,
    status      TEXT,               -- announced|under_construction|commissioned|shelved
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,      -- the statement's own timestamp (keeps the slip)
    PRIMARY KEY (isin, project, announced_on)
) WITHOUT ROWID;

-- [table] metric_state.order_intake
-- Order intake and order-book cover (25 cases), plus contract price basis (19 cases).
-- SOURCE: concall 'order_book' (1,956 items / 253 ISINs), deck 'Order Book' (3,549 rows
-- / 220 ISINs), exchange order-win announcements. Reader-filled.
-- BUILD: ~40k intake rows, ~30k contracts; reader 5 h.
CREATE TABLE IF NOT EXISTS metric_state.order_intake (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    intake_cr   REAL,
    order_book_cr REAL,
    book_to_bill REAL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end)
) WITHOUT ROWID;

-- [table] metric_state.order_book_contract
CREATE TABLE IF NOT EXISTS metric_state.order_book_contract (
    isin        TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    counterparty TEXT,
    value_cr    REAL,
    price_basis TEXT,               -- fixed|indexed|escalation
    escalation_clause TEXT,
    signed_on   TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, contract_id)
) WITHOUT ROWID;

-- [table] metric_state.company_operating_metrics
-- Operating metrics (stores, orders, volumes, LTV) — NG13, 15 cases.
-- SOURCE: concall/deck statements (cc_items 645k rows, deck_facts 13.6M).
-- BUILD: ~100k metric-period rows; 4 h reader.
CREATE TABLE IF NOT EXISTS metric_state.company_operating_metrics (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    metric      TEXT NOT NULL,
    value       REAL,
    unit        TEXT,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, metric)
) WITHOUT ROWID;

-- [table] metric_state.guidance_vs_actual
-- Guidance vs actual (3 cases + management-credibility reddit cases).
-- SOURCE: concall guidance items (7,420 rows / 403 ISINs) joined to
-- company_metric_series. BUILD: ~25k rows; 30 min after the metric series.
CREATE TABLE IF NOT EXISTS metric_state.guidance_vs_actual (
    isin        TEXT NOT NULL,
    metric      TEXT NOT NULL,
    guided_on   TEXT NOT NULL,
    guided_value REAL,
    guided_unit TEXT,
    period_end  TEXT NOT NULL,
    actual_value REAL,
    beat_miss_pct REAL,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, metric, guided_on, period_end)
) WITHOUT ROWID;

-- [table] metric_state.pass_through_history
-- Measured pass-through lag (2 cases but R07's core): shock quarter -> trough -> recovery.
-- SOURCE: company_metric_series margin x commodity_price_daily shocks, computed.
-- BUILD: ~5k rows; 1 h after both inputs exist.
CREATE TABLE IF NOT EXISTS metric_state.pass_through_history (
    isin          TEXT NOT NULL,
    input_series  TEXT NOT NULL,
    shock_start   TEXT NOT NULL,
    trough_quarter TEXT,
    recovery_quarter TEXT,
    pass_through_pct REAL,
    lag_quarters  INTEGER,
    method        TEXT NOT NULL,    -- margin_trough_v1
    PRIMARY KEY (isin, input_series, shock_start)
) WITHOUT ROWID;

-- [table] metric_state.promoter_pledge_event
-- Pledge events (5 cases). SOURCE: announcement headlines/attachments + quarterly SHP
-- cells. BUILD: ~20k events; 20 min deterministic + 2 h reader.
CREATE TABLE IF NOT EXISTS metric_state.promoter_pledge_event (
    isin        TEXT NOT NULL,
    event_date  TEXT NOT NULL,
    pledgor     TEXT,
    action      TEXT NOT NULL CHECK (action IN ('create','invoke','release','top_up')),
    pledged_pct REAL,
    quantity    REAL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, event_date, pledgor, action)
) WITHOUT ROWID;

-- [table] metric_state.rating_action
-- Rating actions with amounts (13 cases). SOURCE: bse_ann headlines (1.9M rows, 100%
-- SUBCATNAME/DissemDT) + attachment text once NG01 lands.
-- BUILD: ~30k rows; 1 h reader.
CREATE TABLE IF NOT EXISTS metric_state.rating_action (
    isin        TEXT NOT NULL,
    action_date TEXT NOT NULL,
    agency      TEXT,
    instrument  TEXT,
    rating      TEXT,
    outlook     TEXT,
    amount_cr   REAL,
    direction   TEXT CHECK (direction IN ('upgrade','downgrade','reaffirm','watch','default')),
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, action_date, agency, instrument)
) WITHOUT ROWID;

-- [table] metric_state.fund_raise
-- Fund raise and utilisation (10 + 3 cases). SOURCE: board outcome/EGM/placement
-- announcements + AR objects-vs-utilisation note (ar_facts related_party/other notes).
-- BUILD: ~15k raises, ~40k utilisation rows; 4 h reader.
CREATE TABLE IF NOT EXISTS metric_state.fund_raise (
    isin        TEXT NOT NULL,
    raise_id    TEXT NOT NULL,
    instrument  TEXT,               -- qip|ipo|rights|ofs|preferential|buyback
    priced_on   TEXT,
    amount_cr   REAL,
    objects     TEXT,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, raise_id)
) WITHOUT ROWID;

-- [table] metric_state.fund_utilisation
CREATE TABLE IF NOT EXISTS metric_state.fund_utilisation (
    isin        TEXT NOT NULL,
    raise_id    TEXT NOT NULL,
    object      TEXT NOT NULL,
    object_amount_cr REAL,
    utilised_cr REAL,
    as_of       TEXT NOT NULL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, raise_id, object, as_of)
) WITHOUT ROWID;

-- [table] metric_state.market_share_shift
-- Market share shift (12 cases): two companies' disclosed volumes on one product line.
-- SOURCE: company_operating_metrics + industry body volumes (needs_new_fetch).
CREATE TABLE IF NOT EXISTS metric_state.market_share_shift (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    product     TEXT NOT NULL,
    volume      REAL,
    unit        TEXT,
    share_pct   REAL,
    source      TEXT NOT NULL,      -- company_disclosure|industry_body
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, product)
) WITHOUT ROWID;

-- [table] metric_state.tariff_exposure
-- Tariff exposure (10 cases): HS line -> revenue share. SOURCE: US/EU customs schedules
-- (fetch) + company export share (company_revenue_geography).
-- BUILD: ~50k (isin,hs) pairs; 5 h after the schedule is fetched.
CREATE TABLE IF NOT EXISTS metric_state.tariff_exposure (
    isin        TEXT NOT NULL,
    hs_code     TEXT NOT NULL,
    country     TEXT NOT NULL,
    rate_pct    REAL,
    effective_on TEXT,
    revenue_share_pct REAL,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, hs_code, country, effective_on)
) WITHOUT ROWID;

-- [table] metric_state.import_duty_structure
-- Duty structure (5 cases). SOURCE: CBIC notifications (fetch).
CREATE TABLE IF NOT EXISTS metric_state.import_duty_structure (
    hs_code     TEXT NOT NULL,
    notification TEXT NOT NULL,
    description TEXT,
    rate_pct    REAL,
    effective_on TEXT NOT NULL,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (hs_code, notification)
) WITHOUT ROWID;

-- [table] metric_state.industry_capacity_pipeline
-- Industry capacity pipeline (9 cases, NG14). SOURCE: capex_project + PIB/state
-- single-window approvals. BUILD: ~20k rows; 2 h after capex_project.
CREATE TABLE IF NOT EXISTS metric_state.industry_capacity_pipeline (
    basic_industry TEXT NOT NULL,
    isin        TEXT,
    announced_on TEXT NOT NULL,
    capacity    REAL,
    unit        TEXT,
    status      TEXT,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (basic_industry, isin, announced_on)
) WITHOUT ROWID;

-- [table] metric_state.supply_link
-- Listed-to-listed supply links (8 cases, NG22). SOURCE: AR related-party note
-- (575k+ facts) + concall named suppliers; curated edges with evidence.
CREATE TABLE IF NOT EXISTS metric_state.supply_link (
    src_isin    TEXT NOT NULL,
    dst_isin    TEXT NOT NULL,
    relation    TEXT NOT NULL,      -- supplier|customer|jv|parent
    share_of_cost_pct REAL,
    evidence_quote TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (src_isin, dst_isin, relation)
) WITHOUT ROWID;

-- [table] metric_state.bank_deposit_rate
-- Bank tables (deposit cards, loan repricing) — 5 + 6 cases.
-- SOURCE: AR deposit schedule, Basel/Pillar-3 disclosures, quarterly decks.
CREATE TABLE IF NOT EXISTS metric_state.bank_deposit_rate (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    bucket      TEXT NOT NULL,      -- savings|1y|2y|3y|5y
    rate_pct    REAL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, bucket)
) WITHOUT ROWID;

-- [table] metric_state.bank_loan_book_repricing
CREATE TABLE IF NOT EXISTS metric_state.bank_loan_book_repricing (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    benchmark   TEXT NOT NULL,      -- eblr|mclr|fixed|base_rate
    share_pct   REAL,
    reset_months INTEGER,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, benchmark)
) WITHOUT ROWID;

-- [table] metric_state.subsidy_register
-- Subsidy/PLI register with expiry (4 cases, NG26). SOURCE: PIB/PLI releases
-- (75,361 pib_releases rows) + AR other-income note.
CREATE TABLE IF NOT EXISTS metric_state.subsidy_register (
    isin        TEXT NOT NULL,
    scheme      TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    amount_cr   REAL,
    expiry_on   TEXT,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, scheme, period_end)
) WITHOUT ROWID;

-- [table] metric_state.competitor_action
-- Competitor actions dated (3 cases). SOURCE: concall price-cut statements + filings.
CREATE TABLE IF NOT EXISTS metric_state.competitor_action (
    isin        TEXT NOT NULL,      -- the actor
    target_isin TEXT,               -- who it hits
    action      TEXT NOT NULL,      -- price_cut|price_hike|capacity_add|exit
    magnitude_pct REAL,
    effective_on TEXT,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, effective_on, action)
) WITHOUT ROWID;

-- [table] metric_state.company_kmp
-- KMP/board person-role-date (3 cases, NG04). SOURCE: AR remuneration (744,758 facts)
-- and governance (585,204), board_meetings (120,451 rows, purpose 100%).
CREATE TABLE IF NOT EXISTS metric_state.company_kmp (
    isin        TEXT NOT NULL,
    person      TEXT NOT NULL,
    role        TEXT NOT NULL,
    from_date   TEXT NOT NULL,
    to_date     TEXT,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, person, role, from_date)
) WITHOUT ROWID;

-- [table] metric_state.entity_relations
-- Auditor-firm and parent/subsidiary relations (3 cases, NG03). SOURCE: ar_facts
-- category in (auditor, auditor_report, subsidiary, subsidiaries) — 201,051 + 494,209
-- + 384,628 facts held.
CREATE TABLE IF NOT EXISTS metric_state.entity_relations (
    src_isin    TEXT,
    src_name    TEXT NOT NULL,
    dst_name    TEXT NOT NULL,
    relation    TEXT NOT NULL,      -- auditor|subsidiary|associate|jv|parent
    valid_from  TEXT,
    valid_to    TEXT,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (src_name, dst_name, relation)
) WITHOUT ROWID;

-- [table] metric_state.audit_opinion_detail
-- Audit opinion detail (10 cases, NG02). SOURCE: results_xbrl.filings.audit_opinion
-- (66,911 of 106,613 filled) + company_forensic_health.has_qualified_audit_opinion
-- (4,065 rows FY22-FY27) + AR auditor report text for EOM/KAM.
-- BUILD: 106k rows; 2 h reader over AR auditor sections.
CREATE TABLE IF NOT EXISTS metric_state.audit_opinion_detail (
    isin         TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    filing_kind  TEXT NOT NULL,     -- quarterly|annual
    opinion_type TEXT,              -- unmodified|qualified|adverse|disclaimer
    eom          INTEGER,           -- emphasis of matter present
    going_concern INTEGER,          -- material uncertainty stated
    kam          INTEGER,           -- key audit matters listed
    quote        TEXT,
    source_doc_id TEXT,
    known_at     TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, filing_kind)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS metric_state.ix_crp_isin_known ON company_result_pit(isin, known_at);

CREATE INDEX IF NOT EXISTS metric_state.ix_xcm_metric ON xbrl_concept_map(metric_key);

CREATE INDEX IF NOT EXISTS metric_state.ix_cms_metric_period ON company_metric_series(metric_key, period_end);

CREATE INDEX IF NOT EXISTS metric_state.ix_cms_isin_known ON company_metric_series(isin, known_at);

CREATE INDEX IF NOT EXISTS metric_state.ix_csp_seg_period ON company_segment_pnl(segment, period_end);

CREATE INDEX IF NOT EXISTS metric_state.ix_csp_isin_known ON company_segment_pnl(isin, known_at);

CREATE INDEX IF NOT EXISTS metric_state.ix_cic_cover ON company_interest_cover(cover_x);

CREATE INDEX IF NOT EXISTS metric_state.ix_cpr_isin_date ON company_price_revision(isin, announced_on);

CREATE INDEX IF NOT EXISTS metric_state.ix_ccs_input ON company_cost_structure(input_key, period_end);

CREATE INDEX IF NOT EXISTS metric_state.ix_capex_status ON capex_project(status, target_on);

CREATE INDEX IF NOT EXISTS metric_state.ix_gva_metric ON guidance_vs_actual(metric, period_end);


-- =====================================================================================
-- 5. chunks_v3.db - the text layer (docs, chunks, tags, FTS5, vector refs).
--    source_class='opinion' is how the opinions family (10) is served: no separate
--    opinions.db. Vectors are NOT in SQLite (3.4M x 4096 f32 = 56 GB); chunk_vec_ref
--    bridges to a NumPy/FAISS index folder per model.
-- =====================================================================================

-- One row per document we are allowed to cite. doc_id is stable and content-addressed
-- when we hold the bytes ('sha256:...'), else '<source>:<native id>'.
-- BUILD: ~150k docs in FY25+ scope (9.4k concalls, 13.0k decks, 14.4k ARs, 41.6k results
-- notes, ~65k material announcements, macro docs) — 12 min for the registry pass.
CREATE TABLE IF NOT EXISTS chunks_v3.doc (
    doc_id          TEXT PRIMARY KEY,
        -- SOURCE: sha256 of the original bytes (raw store), else '<source>:<native id>'
    sha256          TEXT,
        -- SOURCE: reality_engine/raw_store.py content address
    source          TEXT NOT NULL,
        -- SOURCE: raw_documents.source_type normalized (held, 39,645 rows)
    doc_type        TEXT NOT NULL,
        -- SOURCE: corporate_documents.doc_type mapped to (concall|deck|annual_report|
        --         results_notes|announcement|pib|budget|rbi|news|offer)
    source_class    TEXT NOT NULL DEFAULT 'truth'
                    CHECK (source_class IN ('truth','opinion')),
        -- SOURCE: constant per store; opinions never enter the default search
    isin            TEXT,
        -- SOURCE: corporate_documents.isin (100% fill, 127,253 rows)
    symbol_at_time  TEXT,
        -- SOURCE: symbol_isin_history (9,360 rows) resolved at known_at, not today
    title           TEXT,
        -- SOURCE: corporate_documents.title / bse_ann.HEADLINE / PIB title
    event_date      TEXT,
        -- SOURCE: corporate_documents.call_date (4.7% fill) else BSE DT_TM / NEWS_DT
    known_at        TEXT NOT NULL,
        -- SOURCE: corporate_documents.bse_dissem_ts (59% fill) > publication_date (37%)
        --         > results_xbrl.filings.dissem_ts (95%) > bse_ann.DissemDT (100% of
        --         announcements) > letterhead/folder name (pit_conf 0.6-0.8)
    known_at_src    TEXT NOT NULL,
    pit_conf        REAL NOT NULL DEFAULT 1.0 CHECK (pit_conf >= 0 AND pit_conf <= 1),
    fiscal_period   TEXT,
        -- SOURCE: corporate_documents.fiscal_period_end / title parser / results period_end
    page_count      INTEGER,
    parse_route     TEXT,
        -- SOURCE: pymupdf_text | ocr | html_text | xbrl | asr | manual
    quality_grade   TEXT NOT NULL DEFAULT 'A' CHECK (quality_grade IN ('A','B','C')),
    char_count      INTEGER,
    raw_path        TEXT,
        -- SOURCE: raw store path under D:/RealityEngine/raw (sha256-addressed)
    raw_url         TEXT,
        -- SOURCE: corporate_documents.source_url / bse_ann attachment URL
    build_run       TEXT,
    needs_ocr       INTEGER NOT NULL DEFAULT 0
);

-- [table] chunks_v3.chunk
-- One row per chunk. body is a verbatim slice of the parsed ORIGINAL; header is metadata.
-- BUILD: ~3.4M chunks (document_chunks today is 2,939,096; v3 adds announcements and
-- notes), ~9 GB with FTS. Chunk pass: 150k docs x ~1.4 s/doc pymupdf at 8 workers = 260 min.
CREATE TABLE IF NOT EXISTS chunks_v3.chunk (
    chunk_id        INTEGER PRIMARY KEY,
    doc_id          TEXT NOT NULL REFERENCES doc(doc_id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    header          TEXT NOT NULL,
        -- "SYMBOL · doc type · fiscal period · section/speaker · filed DATE" (searchable)
    body            TEXT NOT NULL,
    char_len        INTEGER NOT NULL,
    section         TEXT,
        -- SOURCE: chunker_v2 section detector (MD&A, segment note, notes, Q&A, KAM ...)
    speaker         TEXT,
        -- SOURCE: concall turn parser
    speaker_role    TEXT CHECK (speaker_role IN ('management','analyst','moderator','unknown')),
    unit_kind       TEXT,
        -- qa_pair|opening_remark|turn|slide|note|clause|paragraph|table_row
    page_from       INTEGER, page_to INTEGER,
    span_start      INTEGER, span_end INTEGER,
        -- char offsets into the parsed text (replay/compare, never used for search)
    isin            TEXT,
    symbol_at_time  TEXT,
    doc_type        TEXT NOT NULL,
    source_class    TEXT NOT NULL,
    known_at        TEXT NOT NULL,
    event_date      TEXT,
    fiscal_period   TEXT,
    fiscal_confidence REAL,
    n_numbers       INTEGER NOT NULL DEFAULT 0,
        -- SOURCE: deterministic regex count (AUDIT_PRICE §4.2), not a model
    forward_looking INTEGER NOT NULL DEFAULT 0,
        -- SOURCE: deterministic rule (§4.4 overhaul): guidance verbs + future period
    quality_grade   TEXT NOT NULL DEFAULT 'A',
    pit_conf        REAL NOT NULL DEFAULT 1.0,
    content_tags    TEXT,
        -- display copy only; the FILTER reads chunk_tag (PK order tag,chunk_id)
    UNIQUE (doc_id, chunk_index)
);

-- [table] chunks_v3.chunk_vec_ref
-- Dense vectors do NOT live in SQLite: 3.4M x 4096 float32 = 56 GB, which cannot be read
-- inside the 2 s budget. Vectors live in a memory-mapped .npy per model; this table is the
-- id bridge. QUERY_LAYER.md §5.3 explains why dense runs only on a filtered candidate set.
-- BUILD: one row per (chunk, model) for the existing vector_index_nemotron8b = 1.1M rows;
-- 2 min (pure id copy).
CREATE TABLE IF NOT EXISTS chunks_v3.chunk_vec_ref (
    chunk_id  INTEGER NOT NULL,
    model     TEXT NOT NULL,        -- nemotron8b | qwen8b_ar | bge_small
    row_idx   INTEGER NOT NULL,     -- row in <model>.npy
    dim       INTEGER NOT NULL,
    PRIMARY KEY (model, chunk_id)
) WITHOUT ROWID;

-- [table] chunks_v3.tag_vocab
CREATE TABLE IF NOT EXISTS chunks_v3.tag_vocab (
    tag        TEXT PRIMARY KEY,
    axis       TEXT NOT NULL,       -- content|event|numeric|quality|guidance
    label      TEXT NOT NULL,
    definition TEXT NOT NULL,
    excludes   TEXT,
    live       INTEGER NOT NULL DEFAULT 1
);

-- [table] chunks_v3.chunk_tag
-- Multi-value tags. PK order makes "all chunks with tag X" a range scan; the second
-- index makes "tags of this chunk" a point lookup.
-- BUILD: ~4 tags/chunk x 3.4M = 13M rows worst case; deterministic tags cover ~80%,
-- model tags gated by precision >= 0.90 (overhaul D6). 12 min.
CREATE TABLE IF NOT EXISTS chunks_v3.chunk_tag (
    tag        TEXT NOT NULL REFERENCES tag_vocab(tag),
    chunk_id   INTEGER NOT NULL REFERENCES chunk(chunk_id) ON DELETE CASCADE,
    tagger     TEXT NOT NULL,       -- deterministic:<rule> | model:<name>:<prompt ver>
    confidence REAL,
    PRIMARY KEY (tag, chunk_id)
) WITHOUT ROWID;

-- [table] chunks_v3.coverage_scorecard
CREATE TABLE IF NOT EXISTS chunks_v3.coverage_scorecard (
    measured_on   TEXT NOT NULL,
    doc_type      TEXT NOT NULL,
    tag           TEXT NOT NULL,
    denom_rows    INTEGER NOT NULL,
    filled_rows   INTEGER NOT NULL,
    fill_rate     REAL NOT NULL,
    checked_n     INTEGER,
    checked_ok    INTEGER,
    precision_est REAL,
    precision_lo  REAL,             -- Wilson 95% lower bound
    status        TEXT NOT NULL CHECK (status IN ('missing','sampled','rolled_out','failed')),
    PRIMARY KEY (measured_on, doc_type, tag)
) WITHOUT ROWID;

-- [table] chunks_v3.build_run
CREATE TABLE IF NOT EXISTS chunks_v3.build_run (
    run_id     TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    doc_type   TEXT,
    docs_in    INTEGER, docs_ok INTEGER, docs_failed INTEGER,
    chunks_out INTEGER, tags_out INTEGER, notes TEXT
);

-- [table] chunks_v3.result_note
-- Results-notes PDFs are their own small table because G9 blocks 8 cases and the reader
-- returns note blocks, not pages. Written by the same chunk job once the PDFs are fetched.
-- BUILD: 41,614 BSE "Result" filings -> ~1 PDF per company-quarter (dedupe) ~= 12k docs,
-- 12 notes/doc = 144k rows; 25 min including the reader call budget.
CREATE TABLE IF NOT EXISTS chunks_v3.result_note (
    note_id     INTEGER PRIMARY KEY,
    doc_id      TEXT NOT NULL REFERENCES doc(doc_id) ON DELETE CASCADE,
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    note_no     TEXT,
    note_title  TEXT,
    body        TEXT NOT NULL,
    known_at    TEXT NOT NULL,
    pit_conf    REAL NOT NULL DEFAULT 1.0,
    UNIQUE (doc_id, note_no)
);

CREATE INDEX IF NOT EXISTS chunks_v3.ix_doc_isin_known ON doc(isin, known_at);

CREATE INDEX IF NOT EXISTS chunks_v3.ix_doc_type_known ON doc(doc_type, known_at);

CREATE INDEX IF NOT EXISTS chunks_v3.ix_doc_sha ON doc(sha256);

CREATE INDEX IF NOT EXISTS chunks_v3.ix_chunk_isin_known ON chunk(isin, known_at);

CREATE INDEX IF NOT EXISTS chunks_v3.ix_chunk_type_known ON chunk(doc_type, known_at);

CREATE INDEX IF NOT EXISTS chunks_v3.ix_chunk_fiscal ON chunk(fiscal_period, doc_type);

CREATE INDEX IF NOT EXISTS chunks_v3.ix_chunk_known ON chunk(known_at);

CREATE INDEX IF NOT EXISTS chunks_v3.ix_cvr_chunk ON chunk_vec_ref(chunk_id);

CREATE INDEX IF NOT EXISTS chunks_v3.ix_chunk_tag_chunk ON chunk_tag(chunk_id);

CREATE INDEX IF NOT EXISTS chunks_v3.ix_rnote_isin_period ON result_note(isin, period_end);

-- Entity bridge: one row per (ISIN, symbol, chunk) so a symbol change cannot lose a chunk.
-- BUILT (107,121 rows in the 60-company pilot); not in SCHEMA_V3 -- added here from the built DDL.
CREATE TABLE IF NOT EXISTS chunks_v3.chunk_entity (
    isin     TEXT NOT NULL,
    symbol   TEXT NOT NULL,
    chunk_id INTEGER NOT NULL,
    PRIMARY KEY (isin, symbol, chunk_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS chunks_v3.ix_ce_chunk ON chunk_entity(chunk_id);

-- [virtual] chunks_v3.chunk_fts
-- FTS5 over header+body. External content: text lives once, in chunk.
-- BUILD: ~3.4M rows; FTS index ~= 1x body size; insert rate ~25k chunks/s batched, so
-- the index add is 3 min on top of the chunk pass.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_v3.chunk_fts USING fts5(
    header, body,
    content='chunk', content_rowid='chunk_id',
    tokenize='unicode61 remove_diacritics 2'
);

-- [trigger] chunks_v3.chunk_ai
CREATE TRIGGER IF NOT EXISTS chunks_v3.chunk_ai AFTER INSERT ON chunk BEGIN
    INSERT INTO chunk_fts(rowid, header, body) VALUES (new.chunk_id, new.header, new.body);
END;

-- [trigger] chunks_v3.chunk_ad
CREATE TRIGGER IF NOT EXISTS chunks_v3.chunk_ad AFTER DELETE ON chunk BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, header, body) VALUES ('delete', old.chunk_id, old.header, old.body);
END;

-- [trigger] chunks_v3.chunk_au
CREATE TRIGGER IF NOT EXISTS chunks_v3.chunk_au AFTER UPDATE ON chunk BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, header, body) VALUES ('delete', old.chunk_id, old.header, old.body);
    INSERT INTO chunk_fts(rowid, header, body) VALUES (new.chunk_id, new.header, new.body);
END;


-- =====================================================================================
-- 6. RETIRED / SUPERSEDED (do not build)
--   results_notes.db  (17,989 rows, live interim)     superseded by chunks_v3.result_note
--                                                     + doc/chunk; keep read-only for replay
--                                                     until the v3 chunk store is complete
--   chunks_v2 / equity_intelligence.document_chunks   frozen after v3 parity, replay only
--   metric_state.db naming note                       pilot file is facts_pilot.db; the
--                                                     domain name is metric_state
--   macro_series.db                                   merged into market_state (one table +
--                                                     nameable views, section 3)
--   opinions.db                                       never needed: source_class='opinion'
--                                                     inside chunks_v3 (family 10)
--   consensus_target / investor-level holdings        NOT IN DATA (paid / not published)
--
-- 7. NOT IN DATA (9 cases; see tasks/SCHEMA_FINAL_CASES_2026-10-29.jsonl class='c')
--   refurbished electronics sales (6)  no published series anywhere
--   analyst consensus / target price (1) paid-only source, excluded by ruling
--   future price on a named date (1)   a forecast, not a stored fact
--   Novelis cost curve (1)             unlisted subsidiary, only consolidated P&L filed
-- =====================================================================================
