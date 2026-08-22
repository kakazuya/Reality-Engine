# Module 03: Storage & Database Schema Architecture

---

## 1. Storage Architecture Overview

The system uses a hybrid local storage paradigm:
1. **SQLite 3 (WAL Mode)**: Structured relational metadata, daily OHLCV and delivery time-series, quarterly financial statements, Telegram forum messages, and FTS5 full-text search indexes.
2. **LanceDB**: Persistent, columnar Arrow-based vector store for high-dimensional text chunk embeddings.
3. **Local NVMe Blob Storage**: Raw PDF concall transcripts, investor presentations, Bhavcopy CSV archives, and raw Telegram screenshot images.

---

## 2. SQLite Configuration & Tuning

To ensure zero database locks, sub-millisecond read times, and high concurrent write performance:

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000; -- 64 MB Page Cache in RAM
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 30000000000; -- 30 GB Memory-Mapped I/O for instant OS file reads
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000; -- Wait 5 seconds before throwing lock error
```

---

## 3. Relational Schema Definitions (`equity_intelligence.db`)

```sql
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
    delivery_spike_ratio REAL, -- Deliverable Volume / 20-Day SMA(Deliverable Volume)
    delivery_conviction_score REAL, -- delivery_spike_ratio * delivery_pct
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
    quarter_end_date DATE NOT NULL, -- e.g., '2026-06-30'
    financial_year TEXT NOT NULL,   -- e.g., 'FY27-Q1'
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (isin) REFERENCES master_companies(isin),
    UNIQUE(isin, quarter_end_date)
);

-- 4. Telegram Forum Posts & Transcribed OCR Data (Layer 3)
CREATE TABLE IF NOT EXISTS telegram_posts (
    id TEXT PRIMARY KEY, -- Composite key: channel_id_message_id
    channel_id TEXT NOT NULL,
    channel_title TEXT NOT NULL,
    thread_topic_id INTEGER DEFAULT 0,
    thread_topic_name TEXT,
    message_id INTEGER NOT NULL,
    raw_message_text TEXT,
    has_media BOOLEAN DEFAULT 0,
    media_file_path TEXT,
    ocr_extracted_text TEXT,
    detected_symbols_json TEXT, -- JSON Array: ["RELIANCE", "TCS"]
    post_timestamp TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. FinanciallyFree Portal Sector & Breadth Snapshot (Layer 3)
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

-- 6. Dynamic Distilled Parameter Definitions (Module 07)
CREATE TABLE IF NOT EXISTS dynamic_parameter_definitions (
    parameter_key TEXT PRIMARY KEY,       -- e.g., 'cyclicality_profile', 'business_sensitivities'
    display_name TEXT NOT NULL,
    data_type TEXT NOT NULL,              -- 'JSON', 'FLOAT', 'STRING', 'BOOLEAN'
    description TEXT,
    category TEXT NOT NULL,               -- 'CYCLICALITY', 'BUSINESS_MODEL', 'GOVERNANCE', 'MACRO'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 7. Distilled Company Parameters (Extensible Entity-Attribute-Value + JSON1 Store)
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

-- 8. Causal Knowledge Graph Nodes & Directed Edges (Module 08)
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id TEXT PRIMARY KEY,             -- e.g., 'MACRO_UNION_BUDGET_2026_RAILWAY_CAPEX', 'STOCK_TITAGARH'
    node_type TEXT NOT NULL,              -- 'MACRO_POLICY', 'COMMODITY', 'SECTOR', 'GEOGRAPHY', 'COMPANY', 'MILITARY_CONFLICT'
    name TEXT NOT NULL,
    metadata_json TEXT NOT NULL,          -- Node attributes (e.g., budget allocation INR Cr, baseline price)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS graph_causal_edges (
    edge_id TEXT PRIMARY KEY,
    source_node_id TEXT NOT NULL,         -- e.g., 'COMMODITY_CRUDE_OIL'
    target_node_id TEXT NOT NULL,         -- e.g., 'COMPANY_ASIAN_PAINTS'
    relationship_type TEXT NOT NULL,      -- 'RAW_MATERIAL_INPUT', 'POLICY_BENEFICIARY', 'SUPPLIER_TO', 'TRANSIT_VULNERABILITY'
    impact_direction TEXT NOT NULL,       -- 'POSITIVE', 'NEGATIVE', 'NEUTRAL', 'ASYMMETRIC'
    elasticity_score REAL,                -- Magnitude multiplier: e.g., -1.8 (% margin shift per 10% commodity shift)
    transmission_mechanism TEXT NOT NULL, -- Detailed explanatory narrative of the transmission chain
    evidence_document_ref TEXT,           -- Document citation: "Budget_2026_Speech_P22", "Concall_FY26Q1"
    confidence_score REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_node_id) REFERENCES graph_nodes(node_id),
    FOREIGN KEY (target_node_id) REFERENCES graph_nodes(node_id)
);

CREATE TABLE IF NOT EXISTS macro_events (
    event_id TEXT PRIMARY KEY,
    event_name TEXT NOT NULL,             -- e.g., 'RED_SEA_CRISIS_FREIGHT_SURGE', 'UNION_BUDGET_CAPEX_EXPANSION'
    category TEXT NOT NULL,               -- 'GEOPOLITICAL', 'BUDGET', 'MONETARY', 'REGULATORY', 'COMMODITY'
    event_date DATE NOT NULL,
    raw_document_path TEXT,
    summary TEXT NOT NULL,
    affected_nodes_json TEXT,             -- JSON Array of root-affected node_ids
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 9. User Drop-In Inbox Ingestion Manifest (Section 8)
CREATE TABLE IF NOT EXISTS inbox_ingestion_manifest (
    file_hash TEXT PRIMARY KEY,           -- SHA-256 of the dropped file
    original_filename TEXT NOT NULL,
    file_type TEXT NOT NULL,              -- 'PDF', 'TXT', 'MD', 'PNG', 'JPG'
    detected_entity_type TEXT NOT NULL,   -- 'COMPANY', 'INDUSTRY', 'SECTOR', 'MACRO'
    target_entity_key TEXT,               -- e.g., 'KAYNES', 'SPECIALTY_CHEMICALS', 'PM_SURYAGHAR'
    summary TEXT NOT NULL,
    extracted_parameters_json TEXT,
    associated_graph_nodes_json TEXT,
    processed_file_path TEXT NOT NULL,
    ingested_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 10. EOD Synthesis & Final High-Conviction Scrip Calls (Layer 4)
CREATE TABLE IF NOT EXISTS eod_scrip_calls (
    date DATE NOT NULL,
    symbol TEXT NOT NULL,
    isin TEXT NOT NULL,
    composite_rank INTEGER NOT NULL,
    technical_score REAL NOT NULL,   -- 0 to 100
    fundamental_score REAL NOT NULL, -- 0 to 100
    alt_sentiment_score REAL NOT NULL, -- 0 to 100
    composite_score REAL NOT NULL,   -- Weighted Aggregate
    current_market_price REAL NOT NULL,
    recommended_entry_range TEXT NOT NULL,
    target_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    risk_reward_ratio REAL NOT NULL,
    conviction_level TEXT CHECK(conviction_level IN ('HIGH_CONVICTION', 'MODERATE', 'SPECULATIVE')),
    llm_synthesis_thesis TEXT NOT NULL,
    key_catalysts_json TEXT,
    key_risks_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(date, symbol),
    FOREIGN KEY(isin) REFERENCES master_companies(isin)
);
```

---

## 4. Full-Text Search Virtual Table (FTS5)

```sql
-- FTS5 Virtual Table for Instant Search Across Transcripts & Disclosures
CREATE VIRTUAL TABLE IF NOT EXISTS intelligence_fts USING fts5(
    symbol,
    isin,
    source_type, -- 'CONCALL', 'INVESTOR_PRESENTATION', 'TELEGRAM_OCR', 'ANNOUNCEMENT'
    document_date,
    document_text,
    content='',
    tokenize='porter unicode61'
);

-- Performance Indices for Rapid Scanning
CREATE INDEX IF NOT EXISTS idx_price_date ON daily_price_delivery(date);
CREATE INDEX IF NOT EXISTS idx_price_spike ON daily_price_delivery(date, delivery_spike_ratio DESC);
CREATE INDEX IF NOT EXISTS idx_price_conviction ON daily_price_delivery(date, delivery_conviction_score DESC);
CREATE INDEX IF NOT EXISTS idx_quarterly_sym_date ON quarterly_financials(symbol, quarter_end_date DESC);
CREATE INDEX IF NOT EXISTS idx_tg_post_time ON telegram_posts(post_timestamp DESC);
```

---

## 5. Storage Retention & Maintenance Policies

1. **Daily Bhavcopy Flat Files**: Kept in `./data/bhavcopy/YYYY/` (Compressed to `.tar.gz` quarterly). Total footprint: $<1.5\text{ GB/Year}$.
2. **PDF Documents**: Stored under `./data/pdfs/YYYY/MM/`. Concall PDFs older than 180 days have their raw text preserved in SQLite/LanceDB while raw PDF binaries are pruned.
3. **Telegram Images**: Screenshots older than 60 days are purged from disk after ensuring OCR text and symbol associations are saved in `telegram_posts`.
4. **SQLite Database Auto-Vacuum**: Run `PRAGMA optimize;` every Sunday during market off-hours.
