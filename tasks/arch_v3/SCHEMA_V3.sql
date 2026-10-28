-- =====================================================================================
-- REALITY ENGINE — SCHEMA V3 (2026-10-28)
-- Designed against tasks/master_bank/MASTER_BANK.jsonl (1,030 cases) and
-- tasks/arch_v3/CASE_MAP.jsonl (one row per case: planner chain, table.columns, status).
--
-- Authority: tasks/FRAMEWORK.md; tasks/ARCHITECTURE_OVERHAUL_2026-10-27.md (Manager
-- review overrides the rest of that doc); this file extends both. Where this file
-- disagrees with tasks/QUERY_ARCHITECTURE_PILOT_PLAN_2026-10-28.md it is deliberate and
-- the reason is in tasks/arch_v3/QUERY_LAYER.md §0.
--
-- This script is a DESIGN DOCUMENT that parses: `sqlite3 :memory: < SCHEMA_V3.sql`.
-- It creates every table in one in-memory database for checking. In production the
-- sections below map to separate files (one writer per file):
--     chunks_v3.db     §A   text: docs, chunks, tags, FTS5, vector refs
--     market_state.db  §B   layer-2 daily state + intervals, layer-3 macro, events
--     metric_state.db  §C   structured numbers derived from XBRL/AR/deck/concall
--     macro_series.db  §D   external dated series (commodity, freight, rain, wages)
-- chunks_v2.db and equity_intelligence.document_chunks are FROZEN after v3 parity.
--
-- CONVENTIONS (enforced by the build check, not just by convention)
--   * every TIMESTAMP column is ISO-8601 text in IST (as_of comparisons are lexicographic)
--   * known_at = the first instant the market could see the row (PIT key); 
--     known_at_src names where that instant came from (bse_dissem|nse_dissem|filing_ts|
--     letterhead|folder_name|drive_btime|telegram|upload|session_close)
--   * pit_conf in [0,1]: 1.0 = exact exchange timestamp; 0.8 = date only; 0.6 = inferred
--   * SOURCE:  each column names its origin (held table.column, or raw store + parser)
--   * BUILD:   rows and minutes are estimates at 8 workers, measured row counts from the
--              2026-10-28 read-only probes (tasks/arch_v3/COVERAGE.md §2 has the table)
--   * INDEX:   every index has "-- serves:" naming the query shape it exists for.
--              No index is added for a shape that SPEED_PLAN.md does not time.
-- =====================================================================================

-- =====================================================================================
-- §A  chunks_v3.db — the text layer. One writer: the chunk-build job.
-- =====================================================================================

PRAGMA journal_mode = WAL;

-- One row per document we are allowed to cite. doc_id is stable and content-addressed
-- when we hold the bytes ('sha256:...'), else '<source>:<native id>'.
-- BUILD: ~150k docs in FY25+ scope (9.4k concalls, 13.0k decks, 14.4k ARs, 41.6k results
-- notes, ~65k material announcements, macro docs) — 12 min for the registry pass.
CREATE TABLE IF NOT EXISTS doc (
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
    build_run       TEXT
);
CREATE INDEX IF NOT EXISTS ix_doc_isin_known ON doc(isin, known_at);
    -- serves: "everything we hold about ISIN X as of T" (EVIDENCE hop 1, the dominant
    --         shape: 978 of 1,030 cases name an ISIN)
CREATE INDEX IF NOT EXISTS ix_doc_type_known ON doc(doc_type, known_at);
    -- serves: "latest concall/deck/AR across the universe before T"
CREATE INDEX IF NOT EXISTS ix_doc_sha ON doc(sha256);
    -- serves: dedupe on ingest; replay by content address

-- One row per chunk. body is a verbatim slice of the parsed ORIGINAL; header is metadata.
-- BUILD: ~3.4M chunks (document_chunks today is 2,939,096; v3 adds announcements and
-- notes), ~9 GB with FTS. Chunk pass: 150k docs x ~1.4 s/doc pymupdf at 8 workers = 260 min.
CREATE TABLE IF NOT EXISTS chunk (
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
CREATE INDEX IF NOT EXISTS ix_chunk_isin_known ON chunk(isin, known_at);
    -- serves: entity-scoped candidate set for hybrid search, and "all quotes by X ≤ T"
CREATE INDEX IF NOT EXISTS ix_chunk_type_known ON chunk(doc_type, known_at);
    -- serves: corpus-wide searches restricted to one doc type as of T
CREATE INDEX IF NOT EXISTS ix_chunk_fiscal ON chunk(fiscal_period, doc_type);
    -- serves: "FY26 concalls", "Q1FY27 decks" filters before ranking
CREATE INDEX IF NOT EXISTS ix_chunk_known ON chunk(known_at);
    -- serves: PIT replay walk (build the store as-of a date for the leakage test)

-- FTS5 over header+body. External content: text lives once, in chunk.
-- BUILD: ~3.4M rows; FTS index ~= 1x body size; insert rate ~25k chunks/s batched, so
-- the index add is 3 min on top of the chunk pass.
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    header, body,
    content='chunk', content_rowid='chunk_id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS chunk_ai AFTER INSERT ON chunk BEGIN
    INSERT INTO chunk_fts(rowid, header, body) VALUES (new.chunk_id, new.header, new.body);
END;
CREATE TRIGGER IF NOT EXISTS chunk_ad AFTER DELETE ON chunk BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, header, body) VALUES ('delete', old.chunk_id, old.header, old.body);
END;
CREATE TRIGGER IF NOT EXISTS chunk_au AFTER UPDATE ON chunk BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, header, body) VALUES ('delete', old.chunk_id, old.header, old.body);
    INSERT INTO chunk_fts(rowid, header, body) VALUES (new.chunk_id, new.header, new.body);
END;

-- Dense vectors do NOT live in SQLite: 3.4M x 4096 float32 = 56 GB, which cannot be read
-- inside the 2 s budget. Vectors live in a memory-mapped .npy per model; this table is the
-- id bridge. QUERY_LAYER.md §5.3 explains why dense runs only on a filtered candidate set.
-- BUILD: one row per (chunk, model) for the existing vector_index_nemotron8b = 1.1M rows;
-- 2 min (pure id copy).
CREATE TABLE IF NOT EXISTS chunk_vec_ref (
    chunk_id  INTEGER NOT NULL,
    model     TEXT NOT NULL,        -- nemotron8b | qwen8b_ar | bge_small
    row_idx   INTEGER NOT NULL,     -- row in <model>.npy
    dim       INTEGER NOT NULL,
    PRIMARY KEY (model, chunk_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_cvr_chunk ON chunk_vec_ref(chunk_id);
    -- serves: given a chunk_id, fetch its vector for rerank

CREATE TABLE IF NOT EXISTS tag_vocab (
    tag        TEXT PRIMARY KEY,
    axis       TEXT NOT NULL,       -- content|event|numeric|quality|guidance
    label      TEXT NOT NULL,
    definition TEXT NOT NULL,
    excludes   TEXT,
    live       INTEGER NOT NULL DEFAULT 1
);

-- Multi-value tags. PK order makes "all chunks with tag X" a range scan; the second
-- index makes "tags of this chunk" a point lookup.
-- BUILD: ~4 tags/chunk x 3.4M = 13M rows worst case; deterministic tags cover ~80%,
-- model tags gated by precision >= 0.90 (overhaul D6). 12 min.
CREATE TABLE IF NOT EXISTS chunk_tag (
    tag        TEXT NOT NULL REFERENCES tag_vocab(tag),
    chunk_id   INTEGER NOT NULL REFERENCES chunk(chunk_id) ON DELETE CASCADE,
    tagger     TEXT NOT NULL,       -- deterministic:<rule> | model:<name>:<prompt ver>
    confidence REAL,
    PRIMARY KEY (tag, chunk_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_chunk_tag_chunk ON chunk_tag(chunk_id);
    -- serves: render the tags of the top-k chunks without scanning the PK

CREATE TABLE IF NOT EXISTS coverage_scorecard (
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

CREATE TABLE IF NOT EXISTS build_run (
    run_id     TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    doc_type   TEXT,
    docs_in    INTEGER, docs_ok INTEGER, docs_failed INTEGER,
    chunks_out INTEGER, tags_out INTEGER, notes TEXT
);

-- Results-notes PDFs are their own small table because G9 blocks 8 cases and the reader
-- returns note blocks, not pages. Written by the same chunk job once the PDFs are fetched.
-- BUILD: 41,614 BSE "Result" filings -> ~1 PDF per company-quarter (dedupe) ~= 12k docs,
-- 12 notes/doc = 144k rows; 25 min including the reader call budget.
CREATE TABLE IF NOT EXISTS result_note (
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
CREATE INDEX IF NOT EXISTS ix_rnote_isin_period ON result_note(isin, period_end);
    -- serves: "note 5 of Q2FY27 results for ISIN X" (case MB0120 pattern)

-- =====================================================================================
-- §B  market_state.db — layer-2 market state (daily), layer-3 macro claims, events.
-- =====================================================================================

-- LAYER 2, daily part. One row per ISIN per session.
-- BUILD: 6,940 master ISINs x 1,936 sessions (2019-01-01..2026-10-23) <= 13.4M rows;
-- measured source px_daily 7.3M rows + mkt_nse_full_daily 4.3M + mkt_bse_eq_daily 7.5M.
-- 15 min (join + shares_out merge + bucket compute).
CREATE TABLE IF NOT EXISTS company_state_daily (
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
CREATE INDEX IF NOT EXISTS ix_csd_date_bucket ON company_state_daily(date, mcap_bucket);
    -- serves: "large caps on 4 Jun 2024 ranked by delivery" (A17 pattern), 
    --         bucket membership as of a date
CREATE INDEX IF NOT EXISTS ix_csd_date_band ON company_state_daily(date, price_band);
    -- serves: "companies in a 5% band on results day" (MB0416)
CREATE INDEX IF NOT EXISTS ix_csd_date_fno ON company_state_daily(date, is_fno);
    -- serves: "F&O names with delivery spike" (reddit ta_delivery_spike)

-- Market-cap bucket as an interval: one row per (isin, bucket) stint.
-- SOURCE: derived from company_state_daily (bucket change detection, 13.4M -> ~14k rows).
CREATE VIEW IF NOT EXISTS mcap_bucket_interval AS
SELECT isin,
       mcap_bucket,
       MIN(date) AS valid_from,
       CASE WHEN MAX(date) = (SELECT MAX(date) FROM company_state_daily)
            THEN NULL ELSE MAX(date) END AS valid_to
FROM company_state_daily
GROUP BY isin, mcap_bucket;
-- serves: "was X a large cap on 2023-06-30" with one range scan; no extra table because
-- the daily rows already answer it and a second copy would be 13.4M duplicated values.

-- Price band as a nameable table (the task and MB0416 ask for it). A view, not a copy:
-- the band is a column on the daily row, so a second 13.4M-row table would only duplicate.
-- SOURCE: price_bands.band (1,054,354 rows, 100% fill, 2019-12-30..2026-09-22) +
-- raw D:/RealityEngine/raw/price_bands + circuit_hits (243,049 rows) for band-lock days,
-- resolved to ISIN and written into company_state_daily.price_band at build time.
CREATE VIEW IF NOT EXISTS price_band_daily AS
SELECT isin, date, price_band AS band,
       CASE WHEN price_band IS NULL THEN 0 ELSE 1 END AS has_band
FROM company_state_daily;
-- serves: "band on results day", "did the band change before the announcement" (MB0416);
-- a PK lookup on company_state_daily(isin, date) — no extra index needed.

-- ISIN-history repair ledger (G0: 83 false changes, 1,370 synthetic ISINs, 1,665 FY25+
-- ISINs absent from master). One row per accepted re-key; the resolver consults it before
-- symbol_isin_history so a split/face-value ISIN change cannot rewrite history.
-- SOURCE: px_bse.sc_code/isin, security_master (8,434 rows), symbol_isin_history (9,360),
-- corporate_actions (18,240), isin_rekey_log (held, write-ahead log of past rekeys).
-- BUILD: ~2,000 rows; 2 days curation (G0 effort 2.0 d), 1 min to write.
CREATE TABLE IF NOT EXISTS isin_rekey_map (
    old_isin    TEXT NOT NULL,
    new_isin    TEXT NOT NULL,
    effective_on TEXT NOT NULL,
    reason      TEXT NOT NULL,      -- split|face_value|merger|demerger|symbol_change|synthetic
    verified    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (old_isin, new_isin)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_irm_effective ON isin_rekey_map(effective_on);
    -- serves: the resolver's "was this ISIN valid on D" check at every resolve hop

-- One row per Nifty index named in the 446 dated constituent-change notices.
-- coverage='snapshot'  : full constituent list held (index_membership / current_*.csv);
-- coverage='derived'   : snapshot derived from held lists (Next 50, LargeMidcap 250,
--                        MidSmallcap 400) -- exact by index definition;
-- coverage='changes_only': no snapshot anywhere, only the dated changes are known, so
--                        the intervals are partial and pit_conf < 1.
CREATE TABLE IF NOT EXISTS index_list (
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

-- Interval table: piecewise constant. One seek answers "was X in Midcap 150 on D".
-- SOURCE: NSE index circulars (new fetch) + index_membership snapshot (300 rows,
-- as_of 2026-09-30) + master_companies.is_nifty50/100/200/500 flags backcast.
-- BUILD: ~8k rows after the circular backfill; 3 min.
CREATE TABLE IF NOT EXISTS company_membership_pit (
    isin        TEXT NOT NULL,
    index_code  TEXT NOT NULL REFERENCES index_list(index_code),
    added_on    TEXT NOT NULL,
    removed_on  TEXT,
    source      TEXT NOT NULL,      -- nse_notice|snapshot_backcast|manual
    pit_conf    REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (isin, index_code, added_on)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_cmp_index_added ON company_membership_pit(index_code, added_on);
    -- serves: "constituents of NIFTY50 on D" (unordered) and index rebalance windows
CREATE INDEX IF NOT EXISTS ix_cmp_index_removed ON company_membership_pit(index_code, removed_on);
    -- serves: "who left the index in 2025" (index_flow cases)

-- SOURCE: company_industry (2,055 rows, current) + master_companies.industry (4,231) +
-- BSE scrip-master history (new fetch). GC4 gap: current snapshot only otherwise.
-- BUILD: 6,940 x ~2 classifications = 14k rows; 5 min.
CREATE TABLE IF NOT EXISTS company_sector_pit (
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
CREATE INDEX IF NOT EXISTS ix_csp_basic ON company_sector_pit(basic_industry, valid_from);
    -- serves: industry peer sets and "industry X as of D" screens
CREATE INDEX IF NOT EXISTS ix_csp_sector ON company_sector_pit(sector, valid_from);
    -- serves: sector-level ripple targets (R02 hop 1)

-- SOURCE: curated theme_map matches (basic_industry/sector/keyword/isin) applied to
-- company_sector_pit + company_business_features. No model needed.
-- BUILD: 20 themes x ~40 members = 800 rows; 20 min curation, 1 min to write.
CREATE TABLE IF NOT EXISTS company_theme_pit (
    isin       TEXT NOT NULL,
    theme      TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to   TEXT,
    source     TEXT NOT NULL,       -- curated_map|opinion_theme
    confidence REAL,
    PRIMARY KEY (isin, theme, valid_from)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_ctp_theme ON company_theme_pit(theme, valid_from);
    -- serves: "theme members on D" (MB0011 gold, dairy/HFC universes, 20 theme cases)

CREATE TABLE IF NOT EXISTS theme_map (
    theme       TEXT NOT NULL,
    match_kind  TEXT NOT NULL CHECK (match_kind IN ('basic_industry','sector','keyword','isin')),
    match_value TEXT NOT NULL,
    weight      REAL NOT NULL DEFAULT 1.0,
    source      TEXT NOT NULL,
    PRIMARY KEY (theme, match_kind, match_value)
) WITHOUT ROWID;

-- SOURCE: shp_index (50,838 rows, isin 49,203, broadcast_at 100%, promoter_pct 100%,
-- public_pct 100%) + shp_facts (30,509 raw XBRL facts) for pledge/encumbrance cells.
-- This table is why NG05 ("shareholding is a 40-row stub") is closed: the view is the
-- stub, shp_index is the live PIT store. BUILD: 50,838 rows; 2 min.
CREATE TABLE IF NOT EXISTS company_ownership_pit (
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
CREATE INDEX IF NOT EXISTS ix_cop_known ON company_ownership_pit(known_at);
    -- serves: PIT replay (return the quarter that was PUBLISHED by as_of, not the quarter
    -- that ends before as_of) — the trap in every promoter-holding case

-- SOURCE: results_xbrl.filings (106,613 rows; taxonomy INDAS 69,520, INTEGRATED 30,227,
-- NBFC 3,903, NONINDAS 1,576; broadcast_ts 96%, dissem_ts 95%) x xbrl_concept_map.
-- BUILD: 45,517 FY25+ filings x ~8 headline metrics = 364k rows; 10 min.
CREATE TABLE IF NOT EXISTS company_result_pit (
    isin         TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    basis        TEXT NOT NULL CHECK (basis IN ('standalone','consolidated')),
    known_at     TEXT NOT NULL,     -- filings.dissem_ts (not period end)
    revenue_cr   REAL, ebitda_cr REAL, pat_cr REAL, ebitda_margin REAL,
    revenue_yoy  REAL, pat_yoy REAL, eps REAL,
    source       TEXT NOT NULL,     -- xbrl|annual_report|deck
    PRIMARY KEY (isin, period_end, basis)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_crp_isin_known ON company_result_pit(isin, known_at);
    -- serves: "latest result known as of T" (every results-day case)

-- LAYER 2, events. The 15:30 rule: a filing after 15:30 belongs to the next session.
-- SOURCE: known_at from every store (truth_duckdb.events 3.3M rows is the spine) mapped
-- to the NSE trading calendar. BUILD: 3.3M events -> 3.3M rows; 6 min.
CREATE TABLE IF NOT EXISTS event_day0 (
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
CREATE INDEX IF NOT EXISTS ix_ed0_isin_sess ON event_day0(isin, session_0);
    -- serves: "what happened around the event for X" -> window join on date
CREATE INDEX IF NOT EXISTS ix_ed0_sess ON event_day0(session_0, event_kind);
    -- serves: "all results filed after close on 12 Aug" (A18) and leakage scans

-- The pre-event window: 10 sessions before day0 to 10 after, normalised.
-- SOURCE: px_daily + daily_price_delivery + insider_trades_v2 (333,712 rows) +
-- bulk_block_deals (271,800). Restrict to material events (~300k) or the table is 69M rows.
-- BUILD: 300k events x 21 offsets = 6.3M rows; 25 min.
CREATE TABLE IF NOT EXISTS event_leakage_window (
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
CREATE INDEX IF NOT EXISTS ix_elw_isin_date ON event_leakage_window(isin, date);
    -- serves: "was there a leak into the result" for one stock (R10)

-- LAYER 3. One row per macro document. SOURCE: raw_documents (39,645) filtered to
-- PIB 75,361 live pib_releases rows, budgets, RBI, Economic Survey + policy_events
-- (21,552 rows, published_at 100%, quote_ok 20,970, companies 21,552, sectors 21,552).
-- BUILD: 80k macro docs; 8 min (no reader).
CREATE TABLE IF NOT EXISTS macro_doc (
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

-- One row per extracted claim (a clause with a direction and a magnitude).
-- SOURCE: policy_events rows (21,552) used verbatim where quote_ok=1, plus a reader over
-- PIB/budget/RBI text for the rest. BUILD: ~60k claims; 10 min deterministic + 4 h reader
-- (single 8-worker pass over 80k docs at ~2 s/doc).
CREATE TABLE IF NOT EXISTS macro_claim (
    claim_id        INTEGER PRIMARY KEY,
    doc_id          TEXT NOT NULL,
    clause_no       TEXT,
    policy_type     TEXT NOT NULL,  -- tariff|subsidy|pli|capex|rate|regulation|tender|tax|other
    instrument      TEXT,
    direction       TEXT NOT NULL CHECK (direction IN ('positive','negative','neutral','mixed')),
    magnitude_value REAL,
    magnitude_unit  TEXT,           -- INR_CRORE|INR_LAKH_CRORE|PERCENT|NONE
    magnitude_raw   TEXT,
    effective_date  TEXT,
    end_date        TEXT,
    quote           TEXT NOT NULL,
    char_start      INTEGER, char_end INTEGER,
    model           TEXT NOT NULL,
    confidence      REAL,
    verified        INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (doc_id) REFERENCES macro_doc(doc_id)
);
CREATE INDEX IF NOT EXISTS ix_mclaim_doc ON macro_claim(doc_id);
    -- serves: "all claims in this budget/PIB release" (evidence list for an answer)
CREATE INDEX IF NOT EXISTS ix_mclaim_type ON macro_claim(policy_type, effective_date);
    -- serves: "tariff claims effective in Aug-2025" (R02/R04 triggers)

-- Which sectors / industries / themes / companies a claim touches. This is G10/policy_target.
-- SOURCE: macro_claim + company_sector_pit + curated sector aliases ('Textiles & Apparel'
-- maps to basic_industry). BUILD: ~3 targets/claim = 180k rows; 15 min after the claim pass.
CREATE TABLE IF NOT EXISTS macro_claim_target (
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
CREATE INDEX IF NOT EXISTS ix_mct_target ON macro_claim_target(target_kind, target_id);
    -- serves: "which claims touch basic_industry='Cables - Electricals' after T" (R02 hop 1)

-- Compatibility view: the ripple bank calls this table policy_target.
CREATE VIEW IF NOT EXISTS policy_target AS
SELECT claim_id, target_kind, target_id, direction, weight, evidence FROM macro_claim_target;
-- serves: R01-R10 cases that name `policy_target` directly

-- Macro-event calendar: elections, verdicts, geopolitical shocks, RBI/budget dates.
-- SOURCE: policy_events (21,552) + macro_events (30 rows, 24 with doc_id) + curated
-- external record. BUILD: ~2k rows; 2 h curation, 1 min to write.
CREATE TABLE IF NOT EXISTS event_calendar (
    event_id   TEXT PRIMARY KEY,
    event_kind TEXT NOT NULL,       -- rbi|budget|election|verdict|geopolitical|commodity_shock
    event_date TEXT NOT NULL,
    scope      TEXT,                -- india|us|eu|global|state:XX
    title      TEXT,
    doc_id     TEXT,
    known_at   TEXT NOT NULL,
    pit_conf   REAL NOT NULL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS ix_ec_date ON event_calendar(event_date, event_kind);
    -- serves: "what macro events were known in the 30 days before this move" (A07)

-- Sector-level FII/DII attribution derived from the deal tape (NG18).
-- SOURCE: mkt_fii_dii_cash (1,935 rows, market-wide) + bulk_block_deals (271,800) +
-- mkt_nsdl_fpi_daily (30,128) joined to company_sector_pit. Label derived, not official.
-- BUILD: 1,936 sessions x ~20 sectors = 39k rows; 15 min.
CREATE TABLE IF NOT EXISTS sector_flow_daily (
    date        TEXT NOT NULL,
    sector      TEXT NOT NULL,
    fii_net_cr  REAL,               -- derived: marquee-institution legs in bulk/block deals
    dii_net_cr  REAL,
    method      TEXT NOT NULL,      -- deal_tape_v1
    PRIMARY KEY (date, sector)
) WITHOUT ROWID;

-- F&O open interest, PCR and max-pain inputs (reddit ta_oi_buildup / ta_pcr_maxpain).
-- SOURCE: NSE F&O bhavcopy (free daily files, not held -> needs_new_fetch). Per-contract.
-- BUILD: 1,936 sessions x ~2.5k contracts = 4.8M rows; 25 min after fetch.
CREATE TABLE IF NOT EXISTS fno_oi_daily (
    date        TEXT NOT NULL,
    underlying  TEXT NOT NULL,
    expiry      TEXT NOT NULL,
    strike      REAL,
    option_type TEXT CHECK (option_type IN ('CE','PE','FUT')),
    oi          REAL, oi_change REAL, volume REAL, settle REAL,
    isin        TEXT,
    PRIMARY KEY (date, underlying, expiry, strike, option_type)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_fno_isin_date ON fno_oi_daily(isin, date);
    -- serves: "OI by strike for X into expiry"

-- IPO grey-market premium and listing-day context (reddit ipo_grey_listing).
-- SOURCE: unofficial grey-market quotes (no official source; pit_conf 0.5) + px_daily for
-- the listing day. BUILD: ~1.1k listings x 5 days = 5.5k rows; 30 min curation.
CREATE TABLE IF NOT EXISTS ipo_grey_market (
    isin       TEXT NOT NULL,
    date       TEXT NOT NULL,
    phase      TEXT NOT NULL CHECK (phase IN ('open','close','listing_eve')),
    gmp_inr    REAL,
    issue_price REAL,
    source     TEXT NOT NULL,       -- unofficial: ipo_watch|investorgain
    pit_conf   REAL NOT NULL DEFAULT 0.5,
    PRIMARY KEY (isin, date, phase)
) WITHOUT ROWID;

-- Ordinary vs special dividend/buyback classification (NG23, 2 cases).
-- SOURCE: corporate_actions (18,240 rows, action_type 100%, ex_date 100%) + announcement
-- text. BUILD: 18k rows; 10 min deterministic + 20 min reader spot-check.
CREATE TABLE IF NOT EXISTS corporate_action_class (
    isin        TEXT NOT NULL,
    ex_date     TEXT NOT NULL,
    action_type TEXT NOT NULL,
    ordinary    INTEGER,            -- 1 ordinary, 0 special/one-off, NULL unknown
    amount_per_share REAL,
    known_at    TEXT NOT NULL,      -- corporate_actions.broadcast_date
    PRIMARY KEY (isin, ex_date, action_type)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_cac_date ON corporate_action_class(ex_date, action_type);
    -- serves: "special dividends declared in FY26" and ex-date price adjustment checks

-- =====================================================================================
-- §C  metric_state.db — the structured-number layer. Every table here is a VIEW over
-- held facts in the sense that its inputs are held; the build is parsing/mapping, not
-- fetching. Reader-filled tables say so and carry the reader cost.
-- =====================================================================================

-- The concept map that unlocks G11: one row per (taxonomy, concept, metric_key, sign).
-- SOURCE: results_xbrl.facts has 554 distinct concepts (measured) across 4 taxonomies;
-- hand-map the 60 metrics the bank needs, leave the rest unmapped.
-- BUILD: 60 metrics x ~4 taxonomies = 240 rows; 1 day curation (G11 effort: 1.0 d).
CREATE TABLE IF NOT EXISTS xbrl_concept_map (
    taxonomy     TEXT NOT NULL,     -- INDAS|INTEGRATED|NBFC|NONINDAS
    concept      TEXT NOT NULL,
    metric_key   TEXT NOT NULL,     -- revenue|ebitda|pat|net_worth|borrowings|npa_gnpa|...
    unit_scale   REAL NOT NULL DEFAULT 1.0,   -- XBRL rupees -> crore = 1e-7
    sign         INTEGER NOT NULL DEFAULT 1,
    basis_default TEXT,             -- standalone|consolidated
    verified     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (taxonomy, concept)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_xcm_metric ON xbrl_concept_map(metric_key);
    -- serves: "which concepts implement metric X" during the metric_series build

-- The full quarterly series the bank asks for (62 cases). Long format so new metrics
-- need no migration. SOURCE: results_xbrl.facts (13,941,210 rows) x xbrl_concept_map,
-- plus 5,000-odd results-note numbers where XBRL is silent.
-- BUILD: 45,517 FY25+ filings x ~20 mapped metrics = 910k rows; 20 min.
CREATE TABLE IF NOT EXISTS company_metric_series (
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
CREATE INDEX IF NOT EXISTS ix_cms_metric_period ON company_metric_series(metric_key, period_end);
    -- serves: cross-section screens and sector aggregates ("median NIM Q1FY27")
CREATE INDEX IF NOT EXISTS ix_cms_isin_known ON company_metric_series(isin, known_at);
    -- serves: "the series as known at T" (PIT replay)

-- Segment P&L (41 cases + 50 ripple hops). SOURCE: ar_facts category='segment'
-- (145,742 facts, 4,217 ISINs, segment name embedded in item, quote+page held) +
-- deck_figures.facts metric 'Segment Revenue' (1,986 rows, 46 ISINs) + XBRL
-- SegmentRevenue (64,033 facts / 36,294 files) ONLY where the context member is
-- recovered by re-parsing the XBRL context (today results_xbrl.facts context='OneD',
-- i.e. the member is lost — that is the real reason this gap exists).
-- BUILD: 145k parsed facts -> ~35k segment rows; 45 min deterministic + 2 h validation.
CREATE TABLE IF NOT EXISTS company_segment_pnl (
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
CREATE INDEX IF NOT EXISTS ix_csp_seg_period ON company_segment_pnl(segment, period_end);
    -- serves: "who has the largest X segment in FY26" and peer segment compares
CREATE INDEX IF NOT EXISTS ix_csp_isin_known ON company_segment_pnl(isin, known_at);

-- Working-capital days (25 cases). Computed, never copied (annual_financials has no days).
-- SOURCE: XBRL TradeReceivables/Inventories/TradePayables + Revenue/COGS via concept map;
-- AR receivables_ageing (132,937 facts) for the ageing split.
-- BUILD: 6,940 ISINs x 8 years = 55k rows; 15 min.
CREATE TABLE IF NOT EXISTS company_working_capital (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    basis       TEXT NOT NULL CHECK (basis IN ('standalone','consolidated')),
    receivables_cr REAL, inventory_cr REAL, payables_cr REAL, revenue_cr REAL, cogs_cr REAL,
    dso REAL, dio REAL, dpo REAL, ccc REAL,
    source      TEXT NOT NULL,      -- xbrl|ar_schedule
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, basis)
) WITHOUT ROWID;

-- Interest cover computed from EBIT and finance cost (2 cases + the solvency gate).
-- SOURCE: XBRL FinanceCosts/ProfitBeforeTax; measured reason for the table:
-- annual_financials.interest_coverage has 0 rows < 2.5x in 3,245 FY26 rows, so it cannot
-- rank solvency. BUILD: 55k rows; 10 min.
CREATE TABLE IF NOT EXISTS company_interest_cover (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    basis       TEXT NOT NULL,
    ebit_cr     REAL, finance_cost_cr REAL, cover_x REAL,
    source      TEXT NOT NULL,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, basis)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_cic_cover ON company_interest_cover(cover_x);
    -- serves: "companies with cover < 2.5x as of FY26" (solvency screen)

-- Borrowing repricing mix (20 cases). SOURCE: AR borrowings_maturity (94,733 facts) +
-- borrowings (618,365 facts) + rating rationale text.
-- BUILD: 55k rows; 25 min deterministic + 3 h reader.
CREATE TABLE IF NOT EXISTS company_debt_mix (
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

-- Dated price-hike statements (33 cases). One row per (company, product, announcement).
-- SOURCE: concall_facts.cc_items list_name='pricing_and_competition' (5,003 rows) and
-- 'margin_and_cost_commentary' (7,465), deck text, AR MD&A. Reader-filled.
-- BUILD: ~15k statements; reader 3 h at 8 workers.
CREATE TABLE IF NOT EXISTS company_price_revision (
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
CREATE INDEX IF NOT EXISTS ix_cpr_isin_date ON company_price_revision(isin, announced_on);
    -- serves: R01 "when did the dealer price list move after the metal move"

-- Input cost share of COGS (26 cases, R01 chain). SOURCE: ar_facts raw-material
-- consumption note + segment note; share computed against COGS from XBRL.
-- BUILD: 6,940 x 8 years x ~4 inputs = 220k rows; 30 min deterministic + 3 h reader.
CREATE TABLE IF NOT EXISTS company_cost_structure (
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
CREATE INDEX IF NOT EXISTS ix_ccs_input ON company_cost_structure(input_key, period_end);
    -- serves: "all cable makers' copper share in FY26" (R01/R07 cohort)

-- Imported raw material share (11 cases) and FX exposure (9 cases).
-- SOURCE: AR "imported vs indigenous" note (ar_facts), FX hedging note, concall comments.
-- BUILD: 55k rows each; 20 min deterministic + 3 h reader.
CREATE TABLE IF NOT EXISTS company_import_content (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    imported_raw_material_cr REAL,
    imported_share_pct REAL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS company_fx_exposure (
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

-- Cost geography (3 cases) and revenue geography (6 cases + 20 profile cases).
-- SOURCE: segment note (geographical) in ar_facts/company_segment_pnl for revenue;
-- manufacturing location note for cost. geographic_exposure (3,568 rows, undated) is
-- company_id-keyed and cannot answer "as of FY25" — this table can.
-- BUILD: 6,940 x 8 x 3 = 165k rows revenue; 45k rows cost; 40 min.
CREATE TABLE IF NOT EXISTS company_revenue_geography (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    country     TEXT NOT NULL,      -- india|us|europe|row (normalized)
    revenue_share_pct REAL,
    revenue_cr  REAL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, country)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS company_cost_geography (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    location    TEXT NOT NULL,
    cost_share_pct REAL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, location)
) WITHOUT ROWID;

-- Capacity, utilisation and capex projects (55 cases). SOURCE: AR capacity note
-- (ar_facts category='capacity', 129,348 facts / 2,945 ISINs), deck_figures 'Capacity'
-- (4,035 rows / 397 ISINs), concall 'capacity_and_projects' (7,281 items).
-- Reader-filled, but the statement is kept DATED because the slip is the answer (A01).
-- BUILD: ~60k statements; reader 6 h at 8 workers.
CREATE TABLE IF NOT EXISTS company_capacity_utilisation (
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
CREATE TABLE IF NOT EXISTS capex_project (
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
CREATE INDEX IF NOT EXISTS ix_capex_status ON capex_project(status, target_on);
    -- serves: "commissioning due in FY27 by industry" (NG14 capacity pipeline view)

-- Order intake and order-book cover (25 cases), plus contract price basis (19 cases).
-- SOURCE: concall 'order_book' (1,956 items / 253 ISINs), deck 'Order Book' (3,549 rows
-- / 220 ISINs), exchange order-win announcements. Reader-filled.
-- BUILD: ~40k intake rows, ~30k contracts; reader 5 h.
CREATE TABLE IF NOT EXISTS order_intake (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    intake_cr   REAL,
    order_book_cr REAL,
    book_to_bill REAL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS order_book_contract (
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

-- Operating metrics (stores, orders, volumes, LTV) — NG13, 15 cases.
-- SOURCE: concall/deck statements (cc_items 645k rows, deck_facts 13.6M).
-- BUILD: ~100k metric-period rows; 4 h reader.
CREATE TABLE IF NOT EXISTS company_operating_metrics (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    metric      TEXT NOT NULL,
    value       REAL,
    unit        TEXT,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, metric)
) WITHOUT ROWID;

-- Guidance vs actual (3 cases + management-credibility reddit cases).
-- SOURCE: concall guidance items (7,420 rows / 403 ISINs) joined to
-- company_metric_series. BUILD: ~25k rows; 30 min after the metric series.
CREATE TABLE IF NOT EXISTS guidance_vs_actual (
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
CREATE INDEX IF NOT EXISTS ix_gva_metric ON guidance_vs_actual(metric, period_end);
    -- serves: "who guided margin recovery and delivered" (A03, A14)

-- Measured pass-through lag (2 cases but R07's core): shock quarter -> trough -> recovery.
-- SOURCE: company_metric_series margin x commodity_price_daily shocks, computed.
-- BUILD: ~5k rows; 1 h after both inputs exist.
CREATE TABLE IF NOT EXISTS pass_through_history (
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

-- Pledge events (5 cases). SOURCE: announcement headlines/attachments + quarterly SHP
-- cells. BUILD: ~20k events; 20 min deterministic + 2 h reader.
CREATE TABLE IF NOT EXISTS promoter_pledge_event (
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

-- Rating actions with amounts (13 cases). SOURCE: bse_ann headlines (1.9M rows, 100%
-- SUBCATNAME/DissemDT) + attachment text once NG01 lands.
-- BUILD: ~30k rows; 1 h reader.
CREATE TABLE IF NOT EXISTS rating_action (
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

-- Fund raise and utilisation (10 + 3 cases). SOURCE: board outcome/EGM/placement
-- announcements + AR objects-vs-utilisation note (ar_facts related_party/other notes).
-- BUILD: ~15k raises, ~40k utilisation rows; 4 h reader.
CREATE TABLE IF NOT EXISTS fund_raise (
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
CREATE TABLE IF NOT EXISTS fund_utilisation (
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

-- Market share shift (12 cases): two companies' disclosed volumes on one product line.
-- SOURCE: company_operating_metrics + industry body volumes (needs_new_fetch).
CREATE TABLE IF NOT EXISTS market_share_shift (
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

-- Tariff exposure (10 cases): HS line -> revenue share. SOURCE: US/EU customs schedules
-- (fetch) + company export share (company_revenue_geography).
-- BUILD: ~50k (isin,hs) pairs; 5 h after the schedule is fetched.
CREATE TABLE IF NOT EXISTS tariff_exposure (
    isin        TEXT NOT NULL,
    hs_code     TEXT NOT NULL,
    country     TEXT NOT NULL,
    rate_pct    REAL,
    effective_on TEXT,
    revenue_share_pct REAL,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, hs_code, country, effective_on)
) WITHOUT ROWID;

-- Duty structure (5 cases). SOURCE: CBIC notifications (fetch).
CREATE TABLE IF NOT EXISTS import_duty_structure (
    hs_code     TEXT NOT NULL,
    notification TEXT NOT NULL,
    description TEXT,
    rate_pct    REAL,
    effective_on TEXT NOT NULL,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (hs_code, notification)
) WITHOUT ROWID;

-- Industry capacity pipeline (9 cases, NG14). SOURCE: capex_project + PIB/state
-- single-window approvals. BUILD: ~20k rows; 2 h after capex_project.
CREATE TABLE IF NOT EXISTS industry_capacity_pipeline (
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

-- Listed-to-listed supply links (8 cases, NG22). SOURCE: AR related-party note
-- (575k+ facts) + concall named suppliers; curated edges with evidence.
CREATE TABLE IF NOT EXISTS supply_link (
    src_isin    TEXT NOT NULL,
    dst_isin    TEXT NOT NULL,
    relation    TEXT NOT NULL,      -- supplier|customer|jv|parent
    share_of_cost_pct REAL,
    evidence_quote TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (src_isin, dst_isin, relation)
) WITHOUT ROWID;

-- Bank tables (deposit cards, loan repricing) — 5 + 6 cases.
-- SOURCE: AR deposit schedule, Basel/Pillar-3 disclosures, quarterly decks.
CREATE TABLE IF NOT EXISTS bank_deposit_rate (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    bucket      TEXT NOT NULL,      -- savings|1y|2y|3y|5y
    rate_pct    REAL,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, bucket)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS bank_loan_book_repricing (
    isin        TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    benchmark   TEXT NOT NULL,      -- eblr|mclr|fixed|base_rate
    share_pct   REAL,
    reset_months INTEGER,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, period_end, benchmark)
) WITHOUT ROWID;

-- Subsidy/PLI register with expiry (4 cases, NG26). SOURCE: PIB/PLI releases
-- (75,361 pib_releases rows) + AR other-income note.
CREATE TABLE IF NOT EXISTS subsidy_register (
    isin        TEXT NOT NULL,
    scheme      TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    amount_cr   REAL,
    expiry_on   TEXT,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, scheme, period_end)
) WITHOUT ROWID;

-- Competitor actions dated (3 cases). SOURCE: concall price-cut statements + filings.
CREATE TABLE IF NOT EXISTS competitor_action (
    isin        TEXT NOT NULL,      -- the actor
    target_isin TEXT,               -- who it hits
    action      TEXT NOT NULL,      -- price_cut|price_hike|capacity_add|exit
    magnitude_pct REAL,
    effective_on TEXT,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, effective_on, action)
) WITHOUT ROWID;

-- KMP/board person-role-date (3 cases, NG04). SOURCE: AR remuneration (744,758 facts)
-- and governance (585,204), board_meetings (120,451 rows, purpose 100%).
CREATE TABLE IF NOT EXISTS company_kmp (
    isin        TEXT NOT NULL,
    person      TEXT NOT NULL,
    role        TEXT NOT NULL,
    from_date   TEXT NOT NULL,
    to_date     TEXT,
    source_doc_id TEXT,
    known_at    TEXT NOT NULL,
    PRIMARY KEY (isin, person, role, from_date)
) WITHOUT ROWID;

-- Auditor-firm and parent/subsidiary relations (3 cases, NG03). SOURCE: ar_facts
-- category in (auditor, auditor_report, subsidiary, subsidiaries) — 201,051 + 494,209
-- + 384,628 facts held.
CREATE TABLE IF NOT EXISTS entity_relations (
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

-- Audit opinion detail (10 cases, NG02). SOURCE: results_xbrl.filings.audit_opinion
-- (66,911 of 106,613 filled) + company_forensic_health.has_qualified_audit_opinion
-- (4,065 rows FY22-FY27) + AR auditor report text for EOM/KAM.
-- BUILD: 106k rows; 2 h reader over AR auditor sections.
CREATE TABLE IF NOT EXISTS audit_opinion_detail (
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

-- =====================================================================================
-- §D  macro_series.db — external dated series. Tables exist so the gap is a build,
-- not a design question; the SOURCE line says what must be fetched.
-- =====================================================================================

CREATE TABLE IF NOT EXISTS series_meta (
    series_code TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    source      TEXT NOT NULL,      -- lme|mcx|nse|imd|baltic|wci|mgnrega|rbi
    unit        TEXT NOT NULL,
    cadence     TEXT NOT NULL,      -- daily|weekly|monthly
    fetched_to  TEXT,
    pit_note    TEXT                -- how the release lag is handled
);

-- Commodity/currency series with an explicit release lag (G12, 63 cases).
-- SOURCE: LME/MCX/NSE currency/crude/coal/rubber/cotton/HRC — 13 series are partially
-- held in mkt_commodity_daily (25,255 rows, 2019-01-01..2026-10-06, NO known_at column).
-- BUILD: 40 series x 2,000 days = 80k rows; fetch 1 day + 10 min load.
CREATE TABLE IF NOT EXISTS commodity_price_daily (
    series_code TEXT NOT NULL,      -- lme_copper_3m|mcx_gold|brent|hrc_india|usdinr|...
    date        TEXT NOT NULL,
    close       REAL NOT NULL,
    unit        TEXT NOT NULL,
    known_at    TEXT NOT NULL,      -- exchange close; release lag for monthly series
    pit_conf    REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (series_code, date)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_cpd_date ON commodity_price_daily(date);
    -- serves: cross-series windows ("copper 20 May 2024 -> 30 Sep 2026" A09)

-- SOURCE: container/Baltic/WCI indices (fetch). BUILD: 8 routes x 2,000 = 16k rows; 5 min.
CREATE TABLE IF NOT EXISTS freight_rate_daily (
    route_code TEXT NOT NULL,
    date       TEXT NOT NULL,
    rate_usd   REAL,
    unit       TEXT,
    known_at   TEXT NOT NULL,
    PRIMARY KEY (route_code, date)
) WITHOUT ROWID;

-- SOURCE: IMD district rainfall (fetch). BUILD: 700 districts x 60 months = 42k rows; 5 min.
CREATE TABLE IF NOT EXISTS rainfall_daily (
    region     TEXT NOT NULL,
    date       TEXT NOT NULL,
    rain_mm    REAL,
    departure_pct REAL,
    known_at   TEXT NOT NULL,
    PRIMARY KEY (region, date)
) WITHOUT ROWID;

-- SOURCE: MGNREGA MIS + Labour Bureau (fetch). BUILD: 36 states x 120 months = 4.3k rows.
CREATE TABLE IF NOT EXISTS rural_wage_series (
    state      TEXT NOT NULL,
    month      TEXT NOT NULL,
    wage_inr   REAL,
    known_at   TEXT NOT NULL,
    PRIMARY KEY (state, month)
) WITHOUT ROWID;

-- SOURCE: carrier schedules / port authority (fetch). BUILD: 40 routes x 2,000 = 80k rows.
CREATE TABLE IF NOT EXISTS shipment_transit (
    route_code TEXT NOT NULL,
    date       TEXT NOT NULL,
    transit_days REAL,
    known_at   TEXT NOT NULL,
    PRIMARY KEY (route_code, date)
) WITHOUT ROWID;

-- =====================================================================================
-- NOT BUILT ON PURPOSE (each is a one-line decision in COVERAGE.md §4):
--   consensus_target        paid-only source; excluded by the no-paid-spend rule (3 cases)
--   investor-level holdings not published for Indian listed stocks (1 case)
--   refurbished electronics no published series anywhere (8 cases)
--   opinions.db             G7 blocks 0 master-bank cases; build only when a case needs it
--   document_chunks / chunks_v2  frozen after v3 parity (replay only)
-- =====================================================================================
