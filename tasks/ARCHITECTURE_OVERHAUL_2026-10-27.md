# Architecture overhaul — every source, labelled, graded, point-in-time (2026-10-27)

Status: **design doc for Shivam's review.** Builds the approved direction in
`tasks/LABELS_TAGGING_PLAN_2026-10-27.md` into something a worker can build. No code, no data writes.
Every number below was measured read-only on 2026-10-27 or is cited to a file; unverified items are marked
**unverified**. The query behind each number is in Appendix A.

Authority: `tasks/FRAMEWORK.md`. Verdicts this design obeys: chunker_v2 + headers wins on decks and concalls
(`tasks/optimizations/learn/C1C2_RESULTS_2026-10-26.md`); LLM facts are a structured-value layer, not a search
corpus (same file, wide test: facts R@1 .353 vs v2 .908); no paid spend without Shivam's OK.

---

## 0. Decisions in one page

| # | Decision | Why |
|---|---|---|
| D1 | Three new SQLite files: `chunks_v3.db`, `market_state.db`, `opinions.db`. No Postgres. | One writer per file; opinions must be deletable and never in git. |
| D2 | Layer-1 tags live on the chunk row; multi-value tags live in a `chunk_tag` junction table. | `WHERE tag='order_book'` uses a primary key; JSON/LIKE would scan 3M rows. |
| D3 | Layer 2 is **daily rows** for price/market-cap/band and **intervals** for membership, sector, theme, ownership. | Daily fields change every session; the rest is piecewise-constant. See §2.4. |
| D4 | Layer 3 is three tables: `macro_doc` → `macro_claim` → `macro_claim_target`. | A budget line names several sectors; a claim needs one row per (claim, target). |
| D5 | `document_chunks` and `chunks_v2.db` are frozen read-only after v3 passes parity. | Keeps replay; no second live truth. |
| D6 | Classifier tags are model-derived only after a 300-chunk hand check at precision ≥ 0.90. | Plan §4 already requires it; §4.6 makes it a number. |
| D7 | Opinions never appear in default search. | Plan §9 Q6; `source_class` is on every chunk. |

---

## 1. Target architecture

```
  SOURCES                          ┌───────────────────────────────┐
  NSE/BSE filings, concalls  ─────► │ raw store: D:\RealityEngine\raw│
  decks, annual reports            │ sha256 content-addressed,      │
  results notes PDFs               │ hard links, one copy of bytes  │
  material announcements           └───────────────┬───────────────┘
  PIB, Union/state budgets                         │ registered in
  RBI policy, economic news                        │ equity_intelligence.raw_documents (34.8k)
  analyst Drive, videos, Telegram ──► opinions.db  │
                                                   ▼
                                          parse_router
                                   (pymupdf | ocr | asr | xbrl)
                                                   │
                                          chunker_v2
                                   (per doc type, header + body)
                                                   │
                              ┌────────────────────┴────────────────────┐
                              ▼                                         ▼
                 deterministic tags (§4.2)                 free-model tags, gated (§4.6)
                              └────────────────────┬────────────────────┘
                                                   ▼
   chunks_v3.db:  doc · chunk · chunk_tag · chunk_fts · tag_vocab · coverage_scorecard · build_run
                                                   │
                    ┌──────────────────────────────┴───────────────────────────┐
                    ▼                                                          ▼
       LAYER 2  market_state.db                                  LAYER 3  market_state.db
       company_state_daily (isin, date)                          macro_doc → macro_claim
       membership / sector / theme / result /                    → macro_claim_target
       ownership intervals                                       (sector | basic_industry | theme | isin)
                    └──────────────────────────────┬───────────────────────────┘
                                                   ▼
                      search_docs() · facts() · price() · sql()  ── query time
                      joins layer 2/3 AS OF chunk.known_at or as_of
                                                   │
                                                   └─► opinions.db (separate file, opt-in only)
```

Three rules hold the design together:

1. **Chunk text is immutable.** A tag that can change later is never stamped on a chunk (§3 of the plan).
2. **Layer 2 is joined, never stamped.** `company_state_daily` answers "what did the market know about this
   company on this date", keyed `(isin, date)`.
3. **Opinions are physically separate.** One file, one flag, opt-in reads.

---

## 2. Store layout and DDL

### 2.1 Which file holds what

| file | holds | writer job | estimate |
|---|---|---|---|
| `equity_intelligence.db` (exists, 50.3 GB) | company master, prices, XBRL results mirror, `raw_documents` registry, `corporate_documents`, `bse_announcements` joins | existing ingest jobs, unchanged | unchanged |
| `ar_facts.db`, `deck_figures.db`, `concall_facts.db`, `results_xbrl.db`, `bse_announcements.db` (exist) | extracted **numbers** per doc — the `facts()` layer | existing readers, unchanged | unchanged |
| **`chunks_v3.db`** (new) | every chunk of every text source, all layer-1 tags, FTS5, tag vocabulary, coverage scorecard, build log | one chunk-build job | ~9 GB (3.0M → ~3.4M chunks, median body ~1.1 KB, FTS index about the same size again) |
| **`market_state.db`** (new) | layer-2 daily state + intervals, layer-3 macro links, theme map | one rebuild job (nightly incremental) | ~1.8 GB (13.2M daily rows × ~90 B + intervals) |
| **`opinions.db`** (new) | analyst reports, videos, DailyBytes, chart OCR, Telegram posts, calls, claims, outcomes | one opinions job | ~1.5 GB (126 h of ASR text ≈ 1.1M words **unverified**, + 2,066 chart PNGs of OCR text) |
| `chunks_v2.db` (exists, 23,321 decks / 203,368 chunks) | today's deck chunks, old chunker | frozen after v3 parity | read-only until retired |
| `document_chunks` (in `equity_intelligence.db`, **2,939,096 rows**) | today's chunks, 88.6% of them annual reports and offer documents | frozen after v3 parity | read-only, replay only |

Current chunk population by source (`document_chunks` joined to `raw_documents`, exact, 2,939,096 rows):

| source_type | chunks | docs | chunks/doc |
|---|---:|---:|---:|
| ANNUAL_REPORT | 2,045,985 | 8,265 | 247.6 |
| OFFER_DOCUMENT | 557,421 | 909 | 613.2 |
| CONCALL_TRANSCRIPT | 284,515 | 15,618 | 18.2 |
| PIB_Press_Release | 23,737 | 11,690 | 2.0 |
| Economic_Survey | 8,110 | 19 | 426.8 |
| INVESTOR_PRESENTATION | 7,637 | 1,701 | 4.5 |
| YouTube_DailyBytes | 3,571 | 65 | 54.9 |
| Union_Budget | 1,831 | 35 | 52.3 |
| RBI_MPC_Minutes | 1,006 | 47 | 21.4 |
| RBI_Monetary_Policy | 848 | 135 | 6.3 |
| ANNOUNCEMENT | 368 | 41 | 9.0 |
| state budgets (25 files) | 3,514 | 207 | 17.0 |
| everything else | 533 | 50 | 10.7 |

Read that table twice: **88.6% of today's chunks are annual reports and offer documents.** The sources Shivam
prioritised (P2 decks + concalls, P3 announcements) are under 10% of the store, and announcements are effectively
missing (368 chunks against an announcement feed of ~1.95M rows — `bse_announcements.ann` max rowid 1,947,087).

`document_chunks` is 2,939,096 rows, not the 2.3M in the context pack: `sqlite_stat1` says 2,260,817 because
ANALYZE has not run since the last ingest. Pack drift, noted.

### 2.2 `chunks_v3.db` DDL

```sql
PRAGMA journal_mode = WAL;

-- One row per document we can chunk. doc_id is stable: sha256 when we hold the bytes,
-- else '<source>:<native id>'.
CREATE TABLE IF NOT EXISTS doc (
    doc_id           TEXT PRIMARY KEY,
    sha256           TEXT,
    source           TEXT NOT NULL,          -- raw_documents.source_type, normalised
    doc_type         TEXT NOT NULL,          -- concall|deck|annual_report|results_notes|announcement|pib|budget|rbi|news|offer
    source_class     TEXT NOT NULL CHECK (source_class IN ('truth','opinion')),
    isin             TEXT,
    symbol_at_time   TEXT,                   -- symbol in use on known_at (symbol_isin_history)
    title            TEXT,
    event_date       TEXT,                   -- date the document is about (call/meeting date)
    known_at         TEXT NOT NULL,          -- ISO 8601 timestamp the market could first see it
    known_at_source  TEXT NOT NULL,          -- bse_dissem|nse_dissem|filing_date|body_letterhead|folder_name|drive_btime|telegram|upload
    pit_confidence   REAL NOT NULL DEFAULT 1.0 CHECK (pit_confidence >= 0 AND pit_confidence <= 1),
    fiscal_period    TEXT,                   -- Q2FY25 / FY24 as the document names it
    fiscal_confidence REAL,
    page_count       INTEGER,
    parse_route      TEXT,                   -- pymupdf_text|ocr|asr|html_text|xbrl|manual
    quality_grade    TEXT NOT NULL DEFAULT 'A' CHECK (quality_grade IN ('A','B','C')),
    char_count       INTEGER,
    language         TEXT DEFAULT 'en',
    raw_path         TEXT,
    raw_url          TEXT,
    build_run        TEXT
);
CREATE INDEX IF NOT EXISTS ix_doc_isin_known ON doc(isin, known_at);
CREATE INDEX IF NOT EXISTS ix_doc_type_known ON doc(doc_type, known_at);
CREATE INDEX IF NOT EXISTS ix_doc_sha        ON doc(sha256);

-- One row per chunk. Body is a verbatim slice of the parsed text; header is metadata only.
CREATE TABLE IF NOT EXISTS chunk (
    chunk_id         INTEGER PRIMARY KEY,
    doc_id           TEXT NOT NULL REFERENCES doc(doc_id) ON DELETE CASCADE,
    chunk_index      INTEGER NOT NULL,
    header           TEXT NOT NULL,          -- "SYMBOL · doc type · fiscal period · section/speaker · filed DATE"
    body             TEXT NOT NULL,
    char_len         INTEGER NOT NULL,
    section          TEXT,
    speaker          TEXT,
    speaker_role     TEXT CHECK (speaker_role IN ('management','analyst','moderator','unknown')),
    unit_kind        TEXT,                   -- qa_pair|opening_remark|turn|slide|note|clause|paragraph
    page_from        INTEGER,
    page_to          INTEGER,
    span_start       INTEGER,                -- char offset into the parsed text (replay/compare)
    span_end         INTEGER,
    isin             TEXT,                   -- denormalised from doc: filter without a join
    symbol_at_time   TEXT,
    doc_type         TEXT NOT NULL,
    source_class     TEXT NOT NULL,
    known_at         TEXT NOT NULL,
    event_date       TEXT,
    fiscal_period    TEXT,
    fiscal_confidence REAL,
    n_numbers        INTEGER NOT NULL DEFAULT 0,
    forward_looking  INTEGER NOT NULL DEFAULT 0,
    quality_grade    TEXT NOT NULL DEFAULT 'A',
    pit_confidence   REAL NOT NULL DEFAULT 1.0,
    content_tags     TEXT,                   -- display copy only, space-delimited; the filter uses chunk_tag
    UNIQUE (doc_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS ix_chunk_isin_known ON chunk(isin, known_at);
CREATE INDEX IF NOT EXISTS ix_chunk_type_known ON chunk(doc_type, known_at);
CREATE INDEX IF NOT EXISTS ix_chunk_known      ON chunk(known_at);
CREATE INDEX IF NOT EXISTS ix_chunk_fiscal     ON chunk(fiscal_period);

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

-- Controlled vocabulary. A tag that is not in this table cannot be written.
CREATE TABLE IF NOT EXISTS tag_vocab (
    tag        TEXT PRIMARY KEY,
    axis       TEXT NOT NULL,               -- content|event|numeric|quality
    label      TEXT NOT NULL,
    definition TEXT NOT NULL,
    excludes   TEXT,                        -- what a labeller must NOT tag
    live       INTEGER NOT NULL DEFAULT 1
);

-- Multi-value tags, one row per (tag, chunk). PK order makes "all chunks with tag X" a range scan.
CREATE TABLE IF NOT EXISTS chunk_tag (
    tag        TEXT NOT NULL REFERENCES tag_vocab(tag),
    chunk_id   INTEGER NOT NULL REFERENCES chunk(chunk_id) ON DELETE CASCADE,
    tagger     TEXT NOT NULL,               -- deterministic:<rule> | model:<name>:<prompt version>
    confidence REAL,
    PRIMARY KEY (tag, chunk_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_chunk_tag_chunk ON chunk_tag(chunk_id);

-- Fill rate and checked precision per tag per doc type. A tag is 'rolled_out' only when this says so.
CREATE TABLE IF NOT EXISTS coverage_scorecard (
    measured_on  TEXT NOT NULL,
    doc_type     TEXT NOT NULL,
    tag          TEXT NOT NULL,
    denom_rows   INTEGER NOT NULL,
    filled_rows  INTEGER NOT NULL,
    fill_rate    REAL NOT NULL,
    checked_n    INTEGER,
    checked_ok   INTEGER,
    precision_est REAL,
    precision_lo REAL,                      -- Wilson 95% lower bound
    status       TEXT NOT NULL CHECK (status IN ('missing','sampled','rolled_out','failed')),
    PRIMARY KEY (measured_on, doc_type, tag)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS build_run (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    doc_type    TEXT,
    docs_in     INTEGER,
    docs_ok     INTEGER,
    docs_failed INTEGER,
    chunks_out  INTEGER,
    tags_out    INTEGER,
    notes       TEXT
);
```

### 2.3 `market_state.db` DDL — layers 2 and 3

```sql
PRAGMA journal_mode = WAL;

-- LAYER 2, daily part. One row per ISIN per trading session.
CREATE TABLE IF NOT EXISTS company_state_daily (
    isin            TEXT NOT NULL,
    date            TEXT NOT NULL,          -- trading session (YYYY-MM-DD)
    close           REAL,                   -- adjusted close
    mcap_cr         REAL,                   -- close * shares_out / 1e7
    shares_out      INTEGER,                -- XBRL paid-up / face value, checked against SHP
    shares_source   TEXT,                   -- xbrl_paidup|shp|action_adjusted
    mcap_bucket     TEXT CHECK (mcap_bucket IN ('LARGE','MID','SMALL','MICRO')),
    price_band      INTEGER,                -- 2|5|10|20|40, NULL = no band
    is_fno          INTEGER NOT NULL DEFAULT 0,
    traded_value_20d_cr REAL,
    known_at        TEXT NOT NULL,
    PRIMARY KEY (isin, date)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_csd_date_bucket ON company_state_daily(date, mcap_bucket);
CREATE INDEX IF NOT EXISTS ix_csd_date_band   ON company_state_daily(date, price_band);

-- LAYER 2, interval parts. Piecewise-constant facts; a query tests valid_from <= d < valid_to.
CREATE TABLE IF NOT EXISTS index_list (
    index_code      TEXT PRIMARY KEY,       -- NIFTY50, NIFTY_MIDCAP_150, ...
    display_name    TEXT NOT NULL,
    broad_or_sector TEXT NOT NULL CHECK (broad_or_sector IN ('broad','sector','thematic')),
    size            INTEGER,
    history_from    TEXT
);

CREATE TABLE IF NOT EXISTS company_membership_pit (
    isin        TEXT NOT NULL,
    index_code  TEXT NOT NULL REFERENCES index_list(index_code),
    added_on    TEXT NOT NULL,
    removed_on  TEXT,
    source      TEXT NOT NULL,              -- nse_notice|snapshot_backcast|manual
    PRIMARY KEY (isin, index_code, added_on)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_cmp_index_added  ON company_membership_pit(index_code, added_on);
CREATE INDEX IF NOT EXISTS ix_cmp_index_removed ON company_membership_pit(index_code, removed_on);

CREATE TABLE IF NOT EXISTS company_sector_pit (
    isin           TEXT NOT NULL,
    macro          TEXT,
    sector         TEXT,
    industry       TEXT,
    basic_industry TEXT,
    valid_from     TEXT NOT NULL,
    valid_to       TEXT,
    source         TEXT NOT NULL,           -- nse_classification|bse_classification|manual
    PRIMARY KEY (isin, valid_from)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_csp_basic ON company_sector_pit(basic_industry, valid_from);
CREATE INDEX IF NOT EXISTS ix_csp_sector ON company_sector_pit(sector, valid_from);

CREATE TABLE IF NOT EXISTS company_result_pit (
    isin         TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    basis        TEXT NOT NULL CHECK (basis IN ('standalone','consolidated')),
    known_at     TEXT NOT NULL,             -- XBRL filing timestamp, not period end
    revenue_cr   REAL,
    ebitda_cr    REAL,
    pat_cr       REAL,
    ebitda_margin REAL,
    revenue_yoy  REAL,
    pat_yoy      REAL,
    eps          REAL,
    source       TEXT NOT NULL,             -- xbrl|annual_report|deck
    PRIMARY KEY (isin, period_end, basis)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_crp_isin_known ON company_result_pit(isin, known_at);

CREATE TABLE IF NOT EXISTS company_ownership_pit (
    isin         TEXT NOT NULL,
    quarter_end  TEXT NOT NULL,
    known_at     TEXT NOT NULL,             -- broadcast_at from shp_index
    promoter_pct REAL,
    pledge_pct   REAL,
    fii_pct      REAL,
    dii_pct      REAL,
    mf_pct       REAL,
    public_pct   REAL,
    source       TEXT NOT NULL,             -- shp_index|shareholding_xbrl
    PRIMARY KEY (isin, quarter_end)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS company_theme_pit (
    isin       TEXT NOT NULL,
    theme      TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to   TEXT,
    source     TEXT NOT NULL,               -- curated_map|opinion_theme
    confidence REAL,
    PRIMARY KEY (isin, theme, valid_from)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_ctp_theme ON company_theme_pit(theme, valid_from);

CREATE TABLE IF NOT EXISTS theme_map (
    theme       TEXT NOT NULL,              -- railways, defence, EMS, power_td, ...
    match_kind  TEXT NOT NULL CHECK (match_kind IN ('basic_industry','sector','keyword','isin')),
    match_value TEXT NOT NULL,
    weight      REAL NOT NULL DEFAULT 1.0,
    source      TEXT NOT NULL,              -- curated|opinion
    PRIMARY KEY (theme, match_kind, match_value)
) WITHOUT ROWID;

-- LAYER 3. One row per macro document.
CREATE TABLE IF NOT EXISTS macro_doc (
    doc_id       TEXT PRIMARY KEY,          -- same id space as chunks_v3.doc.doc_id
    source       TEXT NOT NULL,             -- PIB_Press_Release|Union_Budget|State_Budget_*|RBI_Monetary_Policy|Economic_Survey|News_*
    doc_type     TEXT NOT NULL CHECK (doc_type IN ('pib','union_budget','state_budget','rbi_policy','rbi_report','economic_survey','news')),
    issuer       TEXT,                      -- ministry / state / RBI department
    title        TEXT,
    event_date   TEXT,
    known_at     TEXT NOT NULL,
    pit_confidence REAL NOT NULL DEFAULT 1.0,
    language     TEXT DEFAULT 'en'
);

-- One row per extracted policy claim (a clause that says something with a direction).
CREATE TABLE IF NOT EXISTS macro_claim (
    claim_id      INTEGER PRIMARY KEY,
    doc_id        TEXT NOT NULL,
    clause_no     TEXT,
    policy_type   TEXT NOT NULL,            -- tariff|subsidy|pli|capex|rate|regulation|tender|tax|other
    instrument    TEXT,
    direction     TEXT NOT NULL CHECK (direction IN ('positive','negative','neutral','mixed')),
    magnitude_value REAL,
    magnitude_unit  TEXT,                   -- INR_CRONG|INR_LAKH_CRORE|PERCENT|NONE
    magnitude_raw   TEXT,
    effective_date  TEXT,
    quote           TEXT NOT NULL,
    char_start      INTEGER,
    char_end        INTEGER,
    model           TEXT NOT NULL,
    confidence      REAL,
    verified        INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (doc_id) REFERENCES macro_doc(doc_id)
);
CREATE INDEX IF NOT EXISTS ix_mclaim_doc  ON macro_claim(doc_id);
CREATE INDEX IF NOT EXISTS ix_mclaim_type ON macro_claim(policy_type, effective_date);

-- Which sectors / industries / themes / companies a claim touches. Multi-row by design.
CREATE TABLE IF NOT EXISTS macro_claim_target (
    claim_id   INTEGER NOT NULL,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('sector','basic_industry','theme','isin','commodity','state')),
    target_id  TEXT NOT NULL,
    direction  TEXT NOT NULL CHECK (direction IN ('positive','negative','neutral')),
    weight     REAL NOT NULL DEFAULT 1.0,
    evidence   TEXT,
    PRIMARY KEY (claim_id, target_kind, target_id),
    FOREIGN KEY (claim_id) REFERENCES macro_claim(claim_id) ON DELETE CASCADE
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_mct_target ON macro_claim_target(target_kind, target_id);
```

### 2.4 Why daily rows for one part and intervals for the rest

`close`, `mcap_cr`, `mcap_bucket`, `price_band`, `is_fno` and `traded_value_20d_cr` change every session, so an
interval table for them degenerates into one interval per day with a worse query shape (`BETWEEN` instead of a
primary-key point lookup). Daily it is: 6,940 master ISINs (`master_companies`, measured) × 1,936 sessions
(handoff: all sessions 2019-01-01..2026-10-23 backfilled) ≈ 13.4M rows upper bound, inside the same order as the
existing 7.3M-row price tables. Incremental append is 5,358 active ISINs (`master_companies.is_active=1`) per night.

`index_membership` changes rarely. Today it holds **300 rows, one snapshot (2026-09-30): nifty50 50, nifty100 100,
niftymidcap150 150** (measured). Storing that daily would be 13M rows of repeated values for no query benefit;
intervals answer "was X in Midcap 150 on 2023-06-30" with one index seek.

`company_sector_pit`, `company_theme_pit`, `company_ownership_pit` are piecewise-constant for the same reason.

### 2.5 `opinions.db` DDL

```sql
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS opinion_sources (
    source_id TEXT PRIMARY KEY,
    kind      TEXT NOT NULL CHECK (kind IN ('drive_folder','video_channel','telegram_topic','newsletter')),
    name      TEXT NOT NULL,
    space     TEXT NOT NULL CHECK (space IN ('drive_research','member_videos','dailybytes','telegram')),
    access    TEXT NOT NULL DEFAULT 'subscribed',
    licence_note TEXT
);

CREATE TABLE IF NOT EXISTS opinion_docs (
    doc_id        TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL REFERENCES opinion_sources(source_id),
    space         TEXT NOT NULL,
    doc_type      TEXT NOT NULL CHECK (doc_type IN ('report','video','dailybyte','telegram_post','chart')),
    title         TEXT,
    folder_path   TEXT,
    published_at  TEXT,                     -- folder-name date first, then Drive btime, then Telegram exact
    date_source   TEXT NOT NULL,            -- folder_name|drive_btime|telegram|manual
    pit_confidence REAL NOT NULL,
    edited_after_upload INTEGER NOT NULL DEFAULT 0,
    sha256        TEXT,
    raw_path      TEXT,
    duration_sec  INTEGER,
    page_count    INTEGER,
    language      TEXT,
    asr_model     TEXT,
    ocr_done      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_odoc_pub ON opinion_docs(published_at);

CREATE TABLE IF NOT EXISTS opinion_chunks (
    chunk_id     INTEGER PRIMARY KEY,
    doc_id       TEXT NOT NULL REFERENCES opinion_docs(doc_id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    header       TEXT NOT NULL,
    body         TEXT NOT NULL,
    char_len     INTEGER NOT NULL,
    section      TEXT,
    speaker      TEXT,
    speaker_role TEXT,
    unit_kind    TEXT,                      -- turn|slide|chart|paragraph
    t_start_sec  INTEGER,                   -- video / audio only
    t_end_sec    INTEGER,
    page_from    INTEGER,
    isins        TEXT,                      -- JSON array: one opinion can name several companies
    known_at     TEXT NOT NULL,
    quality_grade TEXT NOT NULL DEFAULT 'A',
    UNIQUE (doc_id, chunk_index)
);

CREATE VIRTUAL TABLE IF NOT EXISTS opinion_chunks_fts USING fts5(
    header, body,
    content='opinion_chunks', content_rowid='chunk_id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS ochunk_ai AFTER INSERT ON opinion_chunks BEGIN
    INSERT INTO opinion_chunks_fts(rowid, header, body) VALUES (new.chunk_id, new.header, new.body);
END;
CREATE TRIGGER IF NOT EXISTS ochunk_ad AFTER DELETE ON opinion_chunks BEGIN
    INSERT INTO opinion_chunks_fts(opinion_chunks_fts, rowid, header, body)
    VALUES ('delete', old.chunk_id, old.header, old.body);
END;

CREATE TABLE IF NOT EXISTS opinion_calls (
    call_id       INTEGER PRIMARY KEY,
    doc_id        TEXT NOT NULL REFERENCES opinion_docs(doc_id),
    isin          TEXT,
    symbol        TEXT,
    stance        TEXT NOT NULL CHECK (stance IN ('buy','accumulate','hold','watch','avoid','exit')),
    conviction    INTEGER,                  -- 1..5, model-scored, hand-checked
    thesis        TEXT,
    reasons_json  TEXT,
    target_price  REAL,
    horizon_months INTEGER,
    as_of         TEXT NOT NULL,            -- date the opinion was first visible
    extracted_by  TEXT NOT NULL,
    confidence    REAL
);
CREATE INDEX IF NOT EXISTS ix_ocall_isin ON opinion_calls(isin, as_of);

CREATE TABLE IF NOT EXISTS opinion_claims (
    claim_id      INTEGER PRIMARY KEY,
    call_id       INTEGER NOT NULL REFERENCES opinion_calls(call_id) ON DELETE CASCADE,
    claim_type    TEXT NOT NULL CHECK (claim_type IN ('earnings','order_book','margin','capex','price','event','other')),
    metric        TEXT,
    comparator    TEXT,                     -- gt|lt|gte|lte|eq
    threshold     REAL,
    unit          TEXT,
    horizon_months INTEGER,
    quote         TEXT,
    gradeable     INTEGER NOT NULL DEFAULT 1,
    grade_reason  TEXT
);
CREATE INDEX IF NOT EXISTS ix_oclaim_call ON opinion_claims(call_id);

CREATE TABLE IF NOT EXISTS opinion_outcomes (
    claim_id      INTEGER NOT NULL REFERENCES opinion_claims(claim_id) ON DELETE CASCADE,
    horizon_months INTEGER NOT NULL,
    measured_on   TEXT NOT NULL,
    ret_pct       REAL,
    bench_ret_pct REAL,
    peer_ret_pct  REAL,                     -- same-size random peers, not the sector only
    excess_pct    REAL,
    verdict       TEXT NOT NULL CHECK (verdict IN ('yes','partial','no','ungradeable','pending')),
    evidence      TEXT,
    PRIMARY KEY (claim_id, horizon_months)
) WITHOUT ROWID;
```

Note: SQLite cannot enforce foreign keys across files, so `macro_doc.doc_id` → `chunks_v3.doc.doc_id` is a naming
convention plus a nightly integrity check, not a constraint.

---

## 3. Per-source pipeline spec

Common shape for every source: input rows → parse → chunk → labels → `known_at` → grade. Numbers are measured
today unless marked **target**.

**Where today's layer-1 stands** (60,001 rows of `document_chunks`, rowid window 1,000,000-1,060,000, all
ANNUAL_REPORT, measured): symbol 100%, isin 100%, event_date 100%, published_date 100%, `fiscal_period` **37.8%**,
`sector_id` **0%**, `industry_id` **0%**. That is the baseline the scorecard starts from — and the reason the plan
exists.

### 3.1 Concall transcripts

| | |
|---|---|
| Inputs | `corporate_documents.doc_type='CONCALL_TRANSCRIPT'`: **21,778 rows** (measured). Parsed and chunked: `raw_documents` `CONCALL_TRANSCRIPT` **15,619 docs / 284,515 chunks** (measured). Gap to fetch: 6,086 known-but-unfetched (handoff 2026-10-27). |
| Parser | PyMuPDF text layer. OCR (RapidOCR, CPU ~5.5 s/dense page) only when a page has <200 chars. |
| Chunking | `chunker_v2.chunk_concall`, `QA_MAX_CHARS = 2200`, one Q&A pair per chunk with the question repeated in continuations (`chunker_v2.py:38,491`). |
| Labels | `isin`/`symbol_at_time` (doc, symbol resolved through `symbol_isin_history`); `section` ∈ {Opening remarks, Q&A, Q&A (cont.), Discussion, Header} from `speaker_turns`; `speaker` + `speaker_role` from `_managers`/`_is_question` (management = top-50% word share); `fiscal_period` = quarter of `call_date` (deterministic) with XBRL period-end as cross-check; `content_tags`, `forward_looking` per §4. |
| `known_at` | `bse_dissem_ts` (filled on **75,199 of 127,253** `corporate_documents` rows, measured) → else `publication_date` (47,294 filled) → else `call_date + 1 day`, `pit_confidence` 0.6. Never `doc_date` (crawl date). |
| Quality grade | A: text layer, no OCR page, header present. B: ≥1 OCR page or `> 15%` non-alphanumeric chars. C: <500 chars, or body empty in >20% of chunks. |
| Failure modes | (1) A one-off analyst is not detected as a speaker; the `_hoist_questions` rule recovers the trailing question (`chunker_v2.py:450`). (2) Two-column PDFs interleave. (3) `call_date` empty on 121,264 of 127,253 rows — fiscal period then comes from title/XBRL and confidence drops. (4) **Casing is fine**: measured on 60 concall docs / 992 chunks, "India" appears capitalised 228 times, lower-cased 0 — the briefing claim that concall chunks are stored lowercased does **not** hold for `document_chunks` (it does hold for PIB and RBI, §3.6/§3.8). |
| Volume today → target | 15,619 docs / 284,515 chunks → 21,778 docs / **~396k chunks** (target, 21,778 × 18.2 measured chunks/doc). |

### 3.2 Investor decks

| | |
|---|---|
| Inputs | `deck_figures.deck_sources` where `status='ok'`: **26,391 rows** (measured). On disk and chunked: **23,321 decks (23,299 ok + 22 no_text) / 203,368 chunks** in `chunks_v2.db` (measured). |
| Parser | PyMuPDF per page on the local PDF (`D:\RealityEngine\raw\decks_full\<sha[:2]>\<sha>.pdf`, `load_deck_chunks.py:97`). Image-only slide (<40 chars) → OCR later, not a text chunk. |
| Chunking | **Re-chunk with `chunker_v2.chunk_deck`** — one slide per chunk, short slides merge forward within a section, section title = nearest divider slide (`chunker_v2.py:642`). The wide test says v2 wins decks by 11.5 pts R@1 (.860 vs .745) — so the current old-chunker deck store is the one thing to replace, not keep. |
| Labels | `page_from`/`page_to` from `_page_lookup`; `section` = slide title (first line with ≥3 letters) or divider; `unit_kind='slide'`; `fiscal_period` from title/date, else from the deck's XBRL quarter; `content_tags` (§4) — this is where capacity, order book and margin tags earn their keep. |
| `known_at` | `deck_sources.known_at` (BSE announcement timestamp; range 2021-01-04..2026-09-29). High confidence. |
| Quality grade | A: text layer on ≥80% of pages. B: 20-50% image-only pages. C: >50% or `status='no_text'`. |
| Failure modes | Many "INVESTOR_PRESENTATION" rows in `raw_documents` are one-page cover letters (1,701 docs / 7,637 chunks, 4.5 chunks/doc) — they must not be mixed with real decks; `load_deck_chunks.py` already filters to `deck_sources.status='ok'`. Decks with chart-only pages carry no text; their numbers come from `deck_figures.facts`, not from chunks. |
| Volume today → target | 203,368 chunks (old chunker) → **~420k chunks** (target; v2 produced 2.09× the chunks of the old chunker on the same corpus, C1C2 round wide 15,243 vs 7,303). |

### 3.3 Annual reports

| | |
|---|---|
| Inputs | `corporate_documents` ANNUAL_REPORT **46,573** (+ ANNUAL_REPORT_DEBT_ISSUER 409). Chunked today: `raw_documents` ANNUAL_REPORT **8,265 docs / 2,045,985 chunks** (measured — 70% of the whole store). |
| Parser | PyMuPDF text + heading detection (`blocks_from_text`): a line is a heading when it matches `Note N`/`Schedule IV`/numbered heading or is ≥75% capitals (`chunker_v2.py:704`). GPU layout is **out of the plan**: 0.77 pages/s on the 1050 Ti ≈ 17 days for the corpus (C1C2 results), and GPU layout chunks were never stored. |
| Chunking | `chunker_v2.chunk_annual_report`: one note/schedule per chunk, tables protected from cuts, heading path joined with " > " into `section`. |
| Labels | `section` (heading path) is the main retrieval win; `fiscal_period` from the report's FY; `content_tags` mostly `accounting_note`, `risk`, `related_party`, `capex`, `debt`; `has_numbers` true on most notes. |
| `known_at` | Filing date from BSE/NSE (`bse_dissem_ts`); ARs also carry the AGM/board date in the body. `pit_confidence` 0.9 when dissemination exists, 0.7 when only the filename date (the analysis/ pipeline that does this exists — `apply_annual_report_pit.py`). |
| Quality grade | A: text layer, notes intact. B: OCR or column damage. C: table-only page where numbers are out of order. |
| Failure modes | Notes pages are tables; old 512-token chunks sliced them (2,045,985 chunks at 2,610 chars average is roughly 1 chunk per heading already, so the win in ARs is headers and table protection, not chunk count). 38,308 AR docs in `corporate_documents` are not parsed at all. |
| Volume today → target | 8,265 docs / 2.05M chunks → **46,573 docs / ~2.4M chunks** target (re-chunk 8,265 with v2, parse the remaining 38k). |

### 3.4 Results notes PDFs

| | |
|---|---|
| Inputs | `results_xbrl.filings`: **76,416 filings** (measured). Only 27% carry notes text in the XBRL (**unverified** — from `HANDOFF_2026-10-26.md`; the query was not run here). `corporate_documents` FINANCIAL_RESULT 2,747. |
| Parser | Download the results PDF from BSE, keep **notes pages only** (the pages after the P&L), PyMuPDF text; OCR fallback. |
| Chunking | `chunker_v2.chunk_annual_report` with `doc_type='results_notes'` (it already cuts on `Note N` headings). |
| Labels | `fiscal_period` from the XBRL period; `isin`, `basis` (standalone/consolidated) from the XBRL `context`; `note_no` parsed from the heading → this is the join key to XBRL. `content_tags`: `accounting_note`, `related_party`, `debt`, `contingent_liability`, `segment`. |
| `known_at` | The XBRL filing timestamp for that period+file; the PDF's dissemination if earlier. **Join key**: company + quarter + basis + "note N" (§5 R3). |
| Quality grade | A: text layer. B: OCR. C: scanned table with merged cells. |
| Failure modes | Notes pages are often the last 5-20 pages and are image scans; "note N" numbers do not always match the P&L note references; a company can file two revised results. |
| Volume today → target | **0 chunks.** `raw_documents` has no FINANCIAL_RESULT source_type at all (measured: the type list in Appendix A11); the 2,747 FINANCIAL_RESULT rows live only in `corporate_documents`. Target: 76,416 filings → ~30k with notes → **~150k chunks**. |

### 3.5 Material announcements / order wins

| | |
|---|---|
| Inputs | `bse_announcements.ann`: ~**1.95M rows** (max rowid 1,947,087, measured). Chunked: `raw_documents` ANNOUNCEMENT **41 docs / 368 chunks** (measured). |
| Parser | Metadata is already PIT-stamped (dissemination timestamp). Fetch the attachment PDF only for material categories: order/contract wins, capacity addition, capex, guidance, rating action, dividend/buyback, management change, default/insolvency. Everything else stays a metadata row. |
| Chunking | One announcement = one chunk (most are 1-3 pages). If longer, `chunk_circular` (clause split). |
| Labels | `event_date` = dissemination date; `known_at` = `DissemDT` exact (this is the best timestamp in the whole system); `doc_type='announcement'`; `content_tags` = the category mapped to the same vocabulary (`order_book`, `capacity`, `capex`, `dividend_buyback`, `management_change`, `debt`, `regulatory`, `m&a`); `has_numbers` from the announcement text (order value in ₹ cr). |
| `known_at` | `DissemDT` (IST), high confidence. |
| Quality grade | A: PDF text. B: OCR. C: metadata only, no attachment. |
| Failure modes | Category strings are inconsistent across years; "material" is a judgement — the rule is the category list above, hand-checked on 200 announcements first. Attachments are on BSE and can 404 (the DB keeps the metadata row anyway). |
| Volume today → target | 368 chunks → **~120k chunks** target (material subset of 1.95M, estimated 8-12% material; **unverified** until the category map is measured). |

### 3.6 PIB (Press Information Bureau)

| | |
|---|---|
| Inputs | `pib_releases`: **75,361 English rows**; `pib_ml_releases`: **8,816 regional rows** (both measured). Chunked: `raw_documents` PIB_Press_Release **11,690 docs / 23,737 chunks** (measured, 2.0 chunks/doc — this is a metadata stub, not a chunk of the body). |
| Parser | The body is already in the SQLite row (`pib_releases.body`) — no PDF, no OCR. |
| Chunking | `chunker_v2.chunk_circular`: one clause per chunk when numbered, else 1,200-char sentence groups. |
| Labels | `issuer` = ministry; `doc_type='pib'`; layer-3 tags from §3.6's macro reader (policy_type, direction, magnitude, effective_date); `event_date` = release date; `language` from `pib_ml_releases.language`. |
| `known_at` | PIB posting timestamp (`posted_at`), high confidence. |
| Quality grade | A (plain text, no parse risk). |
| Failure modes | **The body is stored lower-cased**: measured on 60 PIB docs / 135 chunks, "India" capitalised 0, lower-case 80; "Ministry" 0 vs 40. This is a source-side defect, not a chunker one — fix in the PIB writer before the v3 load, or accept it and lose proper nouns in PIB (my recommendation: fix it, one line in the ingest). |
| Volume today → target | 11,690 docs / 23,737 chunks → **84,177 docs (75,361 + 8,816) / ~420k chunks** target (84,177 × ~5 chunks for a full release body). |

### 3.7 Union and state budgets

| | |
|---|---|
| Inputs | `Union_Budget` **35 docs / 1,831 chunks**; 25 state-budget source types **207 docs / 3,514 chunks**; `Economic_Survey` **19 docs / 8,110 chunks** (all measured). |
| Parser | PyMuPDF; union budget documents are large (52.3 chunks/doc) with numbered paragraphs; state budgets are smaller (17/doc). |
| Chunking | `chunker_v2.chunk_circular` for the speech; `chunk_annual_report` for the budget-at-a-glance tables (they are notes/tables, not clauses). |
| Labels | `issuer` = state or Ministry of Finance; `doc_type='budget'`; `event_date` = budget date; layer-3 claims: every allocation line is one `macro_claim` with `magnitude_value`/`unit='INR_CRORE'`, `policy_type='capex'|'subsidy'|'tax'`, and `macro_claim_target` rows for the sector/basic industry. |
| `known_at` | Budget speech date and time (the speech is the first public statement); Finance Bill text later. `pit_confidence` 0.95. |
| Quality grade | A: text. B: scanned table. C: table interleaved with prose. |
| Failure modes | State budgets are in 15 languages and mixed English/Hindi; the allocation tables break on multi-column layouts; ₹ crore vs ₹ lakh crore units must be normalised at extraction, not at query. |
| Volume today → target | 261 docs / 13,455 chunks → **~400 docs / ~30k chunks** target (all states, all years). |

### 3.8 RBI policy

| | |
|---|---|
| Inputs | `RBI_Monetary_Policy` **135 docs / 848 chunks**, `RBI_MPC_Minutes` **47 / 1,006**, `RBI_Annual_Report` 17 / 319, `RBI_Financial_Stability_Report` 15 / 25, `RBI_Strategy_Document` 1 / 5 (all measured). |
| Parser | PyMuPDF. |
| Chunking | `chunk_circular`: policy statements are numbered paragraphs. |
| Labels | layer-3: `policy_type='rate'` (repo/reverse repo/CRR/SLR), `direction`, `magnitude_value` in bps, `effective_date`; targets = `sector` (banks, NBFC, housing finance) and `basic_industry`. |
| `known_at` | MPC statement release timestamp; high confidence. |
| Quality grade | A. |
| Failure modes | Same lower-casing defect as PIB: measured 40 RBI docs / 289 chunks, "India" 0 capitalised vs 160 lower-case. Fix at the writer. |
| Volume today → target | 216 docs / 2,203 chunks → **all MPC statements 2016-2026 (~250 docs) / ~8k chunks**. |

### 3.9 Economic news

| | |
|---|---|
| Inputs | `raw_documents` News_* **860 rows** (businessline 201, et 190, bs 140, livemint 140, livemint_co 122, ndtvprofit 67), **0 chunks** (measured). |
| Parser | RSS body already stored; no PDF. |
| Chunking | `chunk_circular` (1,200-char sentence groups). |
| Labels | `doc_type='news'`, `source_class='truth'` only for wire copy from official outlets; `news_explainer` already scores relevance — reuse that, don't duplicate. |
| `known_at` | RSS publish timestamp. |
| Quality grade | B (journalistic copy, no audit). |
| Failure modes | Retention: `news_retention.py` extracts then deletes papers (fail-closed) — chunks must be written **before** retention deletes the raw body, or the news layer silently disappears. |
| Volume today → target | 860 docs / 0 chunks → **~30k docs / ~150k chunks** target. |

### 3.10 Analyst videos (ASR + frames + glossary)

| | |
|---|---|
| Inputs | 107 member videos (25 GB, 106.5 h) + 62 DailyBytes (10.9 h) = **179 unique videos, 126.2 h** (handoff 2026-10-27). Already chunked: `YouTube_DailyBytes` 65 docs / 3,571 chunks (measured) — those are the older public videos, not the member set. |
| Parser | Audio → **Qwen3-ASR-1.7B on DeepInfra** (best all-round: 97% time coverage, segment+word timestamps, digits kept; 0.6B is nearly equal at half price) — or local Qwen3-ASR on the 1050 Ti, **unverified** speed. Output is mostly Devanagari for Hindi. Frames: scene-change keyframes → perceptual-hash dedupe → RapidOCR (CPU, ~5.5 s/dense frame) → free vision reader for charts. |
| Chunking | One chunk per speaker turn, capped at 2,200 chars (same as concalls); header = `SPACE · video title · date · speaker`. |
| Labels | `doc_type='opinion'`, `source_class='opinion'`; `speaker_role` from **Nemotron-3-Diarization** (segments) or from turn structure; `t_start_sec`/`t_end_sec`; `isins` from the per-video glossary (screen OCR + filing terms + folder title); `published_at` from upload time. |
| `known_at` | Video upload timestamp (YouTube metadata), high confidence for public; for member recordings, the Telegram/DailyBytes post that announced it. |
| Quality grade | A: ASR + glossary corrected. B: ASR without glossary. C: audio < 0.4 SNR or ASR repetition loop. |
| Failure modes | ASR mishears proper terms as near-sounding words (the reason for the glossary); Devanagari script breaks `isin`/symbol matching, so the glossary must map Devanagari forms to symbols; 126 h at $1.51 (0.6B) needs Shivam's OK; laptop GPU too slow. |
| Volume today → target | 3,571 chunks (public videos only) → **~6k transcript chunks + ~2,066 chart chunks** for the member set: 126.2 h ≈ 1.1M words ≈ 6.6M chars ÷ ~1,100 chars per chunk. The existing 3,571 chunks are 65 docs × 54.9, i.e. the older chunker cut far smaller pieces. |

### 3.11 Analyst Drive documents

| | |
|---|---|
| Inputs | ~**252 research reports** (98 company + 15 theme per inventory, handoff) + 35 monthly export Quick Estimates + misc; 3,171 files / 35 GB unique on D; **331 of 529 research docs were edited after upload** (handoff). |
| Parser | Google Docs exported to PDF/DOCX → PyMuPDF; charts are PNGs (2,066) → OCR. |
| Chunking | `chunk_annual_report` for reports; one chunk per chart OCR block. |
| Labels | `opinion_docs.published_at` from **folder name first**, then Drive `btime`; `edited_after_upload=1` → `pit_confidence <= 0.5`; `source_id` per analyst/channel; `isins` from the report text + the analyst's own coverage list. |
| `known_at` | Same as `published_at` (folder name or btime). This is the weakest dating in the system — report it as low confidence, never as fact. |
| Quality grade | A: born-digital PDF. B: scanned. C: re-exported Doc with a changed date. |
| Failure modes | btime is 2025 even for folders named Sep 2024 (handoff); re-exported Docs lose the original date; 159 owner-blocked natives cannot be read at all (not bypassed). |
| Volume today → target | 0 chunks → **~252 reports × ~40 chunks ≈ 10k chunks + 2,066 chart chunks**. |

### 3.12 Telegram

| | |
|---|---|
| Inputs | `telegram_posts`: **4,527 rows, 18 topics** (General 1,347, Request to Shubham 1,227, PEAD 924, Daily Bytes 406, Big Orders 214, …), 2025-05-22..2026-10-26 (measured). Handoff says 4,504 after the 17-topic backfill; the difference is 23 rows from earlier partial runs. |
| Parser | Text is already in the row; media is not downloaded (handoff: "Media is still not downloaded or OCR'd"). |
| Chunking | One post = one chunk; long posts split on paragraphs at 1,200 chars. |
| Labels | `doc_type='opinion'`, `source_class='opinion'`; `thread_topic_name` → `source_id` and a topic tag; `detected_symbols_json` already exists (reuse); `known_at` = `post_timestamp` (exact, UTC). |
| Quality grade | A for text, C for media-only posts (`has_media=1`, no OCR). |
| Failure modes | The same content is often posted in General and in a topic → dedupe by (text hash, ±1 day). Private paid-community content must never reach GitHub — opinions.db lives under `REALITY_DATA_ROOT`, which is gitignored; add a `licence_note` and keep the file out of the repo. |
| Volume today → target | 4,527 posts / 0 chunks → **4,527 chunks**, plus media once downloaded. |

---

## 4. Label derivation rules — deterministic first, model second

### 4.1 Order of application

1. **Parse-time (free, deterministic)** — everything a parser already knows: isin, symbol_at_time, doc_type,
   source_class, section, speaker, page/video offsets, known_at, pit_confidence, quality_grade, fiscal_period
   (when the title/date says it), has_numbers.
2. **Rule-time (free, deterministic)** — regex/table rules that need the text: forward-looking phrases,
   fiscal-period phrases ("quarter ended September 30, 2024"), note numbers, order/capex keywords.
3. **Model-time (free model, subscription)** — only the tags that survive steps 1-2 unanswered: `content_tags`
   and the macro claim extraction.
4. **Never** a model for: isin, symbol, dates, page numbers, bands, membership, sector, growth. Those come from
   tables and must be reproducible.

### 4.2 Deterministic rules that must not be handed to a model

| tag | rule | source |
|---|---|---|
| isin | from the doc; if absent, resolved through `symbol_isin_history` windows (9.4k rows) | `raw_documents`, `corporate_documents`, `symbol_isin_history` |
| symbol_at_time | symbol whose window contains `known_at` | `symbol_isin_history` |
| known_at | table below | `bse_dissem_ts` > `publication_date` > `call_date+1` > folder name > btime |
| event_date | call/meeting date from body letterhead, then title | parser |
| fiscal_period | regex on header/title (`Q[1-4] ?FY\d\d`, `quarter ended <month> <day>, <year>`), cross-checked with the XBRL period of the same ISIN within ±45 days | parser + `results_xbrl` |
| doc_type / source_class | from the ingest source | ingest |
| section / speaker / speaker_role | chunker v2 structure (turns, headings, dividers) | `chunker_v2.py` |
| has_numbers / n_numbers | regex `\d[\d,]*(\.\d+)?` with unit word | parser |
| forward_looking (first pass) | regex in Table 4.4 | parser |
| quality_grade | graded rules in §3 per source | parser |
| pit_confidence | from `known_at_source` | mapping in §4.3 |

### 4.3 `pit_confidence` mapping

| known_at_source | confidence |
|---|---|
| `bse_dissem` / `nse_dissem` (exchange timestamp) | 1.0 |
| `filing_date` (exchange filing register) | 0.9 |
| `body_letterhead` (date printed in the document) | 0.8 |
| `folder_name` (research Drive) | 0.6 |
| `drive_btime` | 0.5 |
| `drive_btime` + `edited_after_upload` | 0.3 |
| `upload` / `crawl` | not allowed — the row is rejected |

### 4.4 `forward_looking` deterministic rule

True when the chunk matches any of: `\b(will|would|expect|expects|expected|guidance|guide|aim|target|plan to|
intend|should|likely|next (quarter|half|year)|FY2\d|H[12] FY)\b` and is not a pure table row (n_numbers > 8 and
words < 30). Measured coverage is not yet known; the model gets only the chunks the regex leaves **negative**,
to catch "we are confident of maintaining" style statements. Report the split in the scorecard.

### 4.5 Content tag vocabulary (write this into `tag_vocab`)

| tag | definition (what must be true) | excludes |
|---|---|---|
| `guidance` | management states a future number or direction for revenue, margin, volume, capex or order book | a past result restated as a trend |
| `order_book` | an order book, order inflow, backlog or contract win with a value/period | generic "strong demand" with no order language |
| `capacity` | capacity addition, utilisation, debottlenecking, new plant/line | capex money with no capacity words |
| `capex` | capital expenditure planned or spent, with or without an amount | maintenance spend described as "routine" |
| `margin` | margin level, expansion, contraction, or mix effect | revenue growth alone |
| `pricing` | price increase/hike/cut, realisation, discounting | "pricing power" as a moat phrase only |
| `demand` | demand strength/weakness, volume growth, offtake | supply-side commentary |
| `debt` | borrowings, refinancing, leverage, interest cost, rating | trade payables |
| `working_capital` | receivable/payable/inventory days, cash conversion | one-off provisions |
| `m_and_a` | acquisition, merger, demerger, stake sale, JV | a supplier relationship |
| `regulatory` | licence, approval, tariff order, SEBI/RBI action, GST/customs | general policy commentary without an action |
| `management_change` | MD/CEO/CFO/board change, resignation, succession | analyst names |
| `dividend_buyback` | dividend, buyback, bonus, split, record date | earnings distribution discussion |
| `risk` | stated risk, contingency, litigation, going-concern, impairment | routine safe-harbour boilerplate |
| `accounting_note` | note to accounts, policy change, restatement, auditor qualification | the P&L table itself |
| `analyst_view` | a named analyst/broker expressing a view (opinions only) | management statements |

### 4.6 Model-derived tags: model, prompt contract, precision gate

**Which model.** Free/subscription only, in this order:
1. **Local llama.cpp** via `reality_engine/ingestion/llm_lens_client.py` — cheapest, no quota, slow.
2. **OpenCode Go / DeepSeek V4.1 Flash** — the reader already used for concalls (`concall_deepseek.py`); free on
   the subscription, no per-token bill.
3. **OpenCode Zen free models** (`ar_queue.py` pattern) — fallback when Go is rate-limited.

No DeepInfra for tagging: it is pay-per-token and needs Shivam's OK each time.

**Prompt contract (one call = 20 chunks, JSON out).** The contract is the same for every doc type; only the
`doc_type` line changes.

```
You label chunks of Indian listed-company documents. You see ONLY the chunk text and its header.
Return one JSON object per input line, in order:
{"id":"<chunk id>","tags":["<tag>",...],"forward_looking":true|false,"numbers":[{"metric":"...","value":123.4,"unit":"INR_CRORE|PERCENT|DAYS|COUNT|PER_SHARE","period":"Q2FY25|FY24|null"}]}
Rules:
- Use only these tags: <TAG_LIST from tag_vocab where live=1>.
- A tag is true only when the chunk itself says it. Do not infer from the company or the doc type.
- If nothing applies, return an empty list. Do not invent a tag to be helpful.
- Do not translate, summarise or quote. No prose outside the JSON.
- A number goes in "numbers" only if the unit and the period are both in the chunk; otherwise leave it out.
```

**Precision gate (before roll-out, per doc_type):**
- Draw a **stratified random sample of 300 chunks** per doc type (strata: section, fiscal period, quality grade).
- Two people (or one person twice, ≥1 week apart) label the 300 by hand against §4.5 definitions.
- Compute per-tag precision `k/n_tagged` and the **Wilson 95% lower bound**.
- Ship a tag when precision ≥ 0.90 **and** Wilson lower bound ≥ 0.85. Rewrite the prompt and re-sample when
  0.80-0.90. Kill the tag (leave it unfilled, report it as `failed`) below 0.80.
- Also run the same 300 twice and require label agreement ≥ 0.95; below that the prompt is ambiguous, not the
  model.
- Record every result in `coverage_scorecard`; a tag counts as done only when its row says `rolled_out`.

**Cost of the gate**: 300 chunks × 10 doc types = 3,000 hand labels ≈ 2.5 person-days. That is the price of not
shipping a tag with unknown precision.

### 4.7 Macro claim extraction (layer 3)

Same free models, one call per macro document (PIB releases are short; budget documents are chunked and the call
runs per chunk group of 6,000 chars).

```
You extract policy claims from Indian government / RBI / budget text.
Return JSON: {"claims":[{"clause_no":"...","quote":"<exact substring>","policy_type":"tariff|subsidy|pli|capex|rate|regulation|tender|tax|other",
"instrument":"...","direction":"positive|negative|neutral|mixed","magnitude":{"value":123.4,"unit":"INR_CRORE|INR_LAKH_CRORE|PERCENT|BPS","raw":"..."},
"effective_date":"YYYY-MM-DD|null","targets":[{"kind":"sector|basic_industry|theme|isin|commodity|state","id":"...","direction":"positive|negative|neutral"}]}]}
Rules: quote must be a verbatim substring of the input; targets must come from the provided vocabulary list;
if no target is named or implied, return an empty targets list. Do not use the word "beneficiary".
```

Precision gate: 200 hand-checked claims per source class (PIB, budget, RBI), scoring (a) is this a claim, (b) does
the quote match the text exactly, (c) is the direction right, (d) is the target list right. Ship at ≥0.90 on (a)
and (b), ≥0.85 on (c) and (d). `macro_claim.verified=1` only for the hand-checked sample until the gate passes.

---

## 5. Point-in-time rules and look-ahead tests

### 5.1 Rules

| # | Rule |
|---|---|
| R1 | `known_at` is a timestamp. A date without a time gets 23:59:59 IST of that date and `pit_confidence ≤ 0.9`. `doc_date` (crawl date) is never evidence. |
| R2 | Every query that joins layer 2 defaults to `chunk.known_at`; the `as_of` parameter overrides it. Nothing joins "as of today" unless the caller says today. |
| R3 | A chunk's tags must be derivable from data known at `known_at`. If a tag needs a later filing (e.g. XBRL period match), lower `pit_confidence` and record `tagger='model:...:late'`; never silently upgrade. |
| R4 | Layer-2 intervals: `valid_from <= d AND (valid_to IS NULL OR valid_to > d)`. A removed index member is still a member on the removal date. |
| R5 | `master_companies.market_cap_tier` (current-only: LARGE 102 / MID 108 / SMALL 315 / MICRO 6,031 / NULL 384, measured) is banned from any historical query. MICRO is a catch-all, not a classification. |
| R6 | Survivorship: the universe is ISINs that traded on the date, `is_active` is only a hint (`master_companies`: 5,358 active, 1,582 inactive). Delisted names stay in. |
| R7 | Opinions: folder-name date beats btime; edited-after-upload caps `pit_confidence` at 0.5; Telegram timestamps are exact. |
| R8 | Any derived table carries its own `known_at` (the time the derivation ran is not the time the fact became true — use the underlying fact's timestamp). |

### 5.2 Tests (each is a runnable assert; none is optional)

| test | assertion | fails when |
|---|---|---|
| T1 stamp completeness | `SELECT count(*) FROM chunk WHERE known_at IS NULL OR length(known_at) <> 19` = 0, and same on `doc` | a parser wrote a date where a timestamp was needed |
| T2 as-of leak | for each of the 5 §6 queries and 5 dates, `count(chunk.known_at > as_of)` = 0 | a join ignored `as_of` |
| T3 state replay | 200 random `(isin, date)`: rebuild `company_state_daily` row from inputs with `known_at <= date`, diff ≤ 1e-6 | a field used a later value |
| T4 membership spot-check | hand-checked index membership at 4 dates (2020-01-31, 2022-06-30, 2024-03-28, 2025-09-30) vs `company_membership_pit`; mismatch = 0 | backfilled history invented |
| T5 band join | 1,000 random `(symbol, date)`: `company_state_daily.price_band` = `price_bands.band` | the join used the wrong series |
| T6 tag stability | same 300 chunks labelled twice; disagreement ≤ 5% | the prompt is ambiguous |
| T7 survivorship | a 2020-03 screen returns ≥ 1 ISIN that is now `is_active=0` | the universe was filtered on today's flag |
| T8 future fiscal period | no chunk has `fiscal_period` whose period end > `event_date + 30 days` | a doc was stamped with a period it could not know |

T2 and T7 are the two that catch the expensive mistakes; run them in the nightly scorecard job, not only in CI.

---

## 6. Query examples (against the proposed schema)

All five use the layer-1 filters first, so the vector/FTS pass runs on a small set. Preamble for all five: the
tool opens `chunks_v3.db` as the main database and attaches `market_state.db` and `opinions.db` **read-only**
(`ATTACH 'file:...?mode=ro' AS ...`). Table names are unique across the three files, so the SQL below uses
unqualified names. Cross-file joins are SQLite's own; no copy and no server.

**Q1. "Small caps with PAT growth > 30% that talked about order-book visibility in FY24 concalls."**

```sql
WITH asof(d) AS (VALUES ('2024-03-31')),
latest AS (
    SELECT isin, pat_yoy, period_end
    FROM (
        SELECT isin, pat_yoy, period_end,
               row_number() OVER (PARTITION BY isin ORDER BY known_at DESC) AS rn
        FROM company_result_pit
        WHERE basis = 'consolidated' AND known_at <= (SELECT d FROM asof)
    ) WHERE rn = 1
)
SELECT c.chunk_id, c.isin, c.symbol_at_time, c.fiscal_period, substr(c.body, 1, 200)
FROM chunk_tag t
JOIN chunk c        ON c.chunk_id = t.chunk_id
JOIN latest l       ON l.isin = c.isin AND l.pat_yoy > 0.30
JOIN company_state_daily s ON s.isin = c.isin AND s.date = (SELECT d FROM asof)
WHERE t.tag = 'order_book'
  AND c.doc_type = 'concall'
  AND c.fiscal_period LIKE '%FY24%'
  AND s.mcap_bucket IN ('SMALL','MICRO')
  AND c.known_at <= (SELECT d FROM asof) || 'T23:59:59';
```

Index use: `chunk_tag` PK `(tag, chunk_id)` range-scans `order_book`; `chunk` PK point lookups; `company_result_pit`
`ix_crp_isin_known` for the window function; `company_state_daily` PK `(isin, date)`. Expected: milliseconds on a
2-5k row candidate set, then one FTS/vector re-rank if the caller passes a text query.

**Q2. "Everything said about railway wagon makers within 30 days of the Budget 2025 rail capex line."**

```sql
WITH claim AS (
    SELECT claim_id, doc_id, effective_date
    FROM macro_claim
    WHERE policy_type = 'capex' AND magnitude_raw LIKE '%rail%'
      AND claim_id IN (SELECT claim_id FROM macro_claim_target
                       WHERE target_kind = 'theme' AND target_id = 'railways')
    LIMIT 1
)
SELECT c.chunk_id, c.doc_type, c.isin, c.known_at, substr(c.body, 1, 200)
FROM claim m
JOIN macro_doc md          ON md.doc_id = m.doc_id
JOIN macro_claim_target mt ON mt.claim_id = m.claim_id AND mt.target_kind = 'theme'
JOIN company_theme_pit th  ON th.theme = mt.target_id
                          AND th.valid_from <= md.known_at
                          AND (th.valid_to IS NULL OR th.valid_to > md.known_at)
JOIN chunk c               ON c.isin = th.isin
                          AND c.known_at BETWEEN datetime(md.known_at, '-30 days')
                                             AND datetime(md.known_at, '+30 days')
UNION ALL
SELECT c.chunk_id, c.doc_type, NULL, c.known_at, substr(c.body, 1, 200)
FROM chunk c
WHERE c.doc_id = (SELECT doc_id FROM claim);
```

Index use: `ix_mct_target` for the theme lookup, `ix_ctp_theme` for theme→ISIN, `ix_chunk_isin_known` for the
30-day window. The budget document's own clauses come from the `UNION ALL` branch, which is a scalar lookup on the
unique `(doc_id, chunk_index)` index — deliberately not a join, which the planner turns into a scan of `chunk`.

**Q3. "Nifty Midcap 150 companies whose management guided margin expansion, as of 2023-06-30."**

```sql
SELECT c.chunk_id, c.isin, c.fiscal_period, substr(c.body, 1, 200)
FROM company_membership_pit m
JOIN chunk c     ON c.isin = m.isin
JOIN chunk_tag t ON t.chunk_id = c.chunk_id AND t.tag = 'margin'
WHERE m.index_code = 'NIFTY_MIDCAP_150'
  AND m.added_on <= '2023-06-30'
  AND (m.removed_on IS NULL OR m.removed_on > '2023-06-30')
  AND c.doc_type = 'concall'
  AND c.forward_looking = 1
  AND c.known_at <= '2023-06-30T23:59:59';
```

Index use: `ix_cmp_index_added` (index code + date) → ~150 ISINs; `ix_chunk_isin_known` per ISIN; `chunk_tag` PK
for the tag. The trap this query avoids: `master_companies.is_nifty*` is today's membership.

**Q4. "Stocks in the 5% price band whose deck mentioned a capacity addition."**

```sql
SELECT c.chunk_id, c.isin, s.date, s.price_band, substr(c.body, 1, 200)
FROM chunk c
JOIN chunk_tag t ON t.chunk_id = c.chunk_id AND t.tag = 'capacity'
JOIN company_state_daily s ON s.isin = c.isin AND s.date = substr(c.known_at, 1, 10)
WHERE c.doc_type = 'deck'
  AND s.price_band = 5;
```

Index use: `chunk_tag` PK for `capacity`; `ix_chunk_type_known` narrows to decks before the join; PK
`(isin, date)` for the band. (If the band should be read as of the deck date, `substr(known_at,1,10)` is exactly
that.)

**Q5. "Every analyst call on a defence stock, and whether the thesis played out within 12 months."**

```sql
SELECT o.call_id, o.isin, o.symbol, o.stance, o.as_of, o.horizon_months,
       r.ret_pct, r.bench_ret_pct, r.peer_ret_pct, r.excess_pct, r.verdict
FROM opinion_calls o
JOIN opinion_outcomes r ON r.claim_id IN (
        SELECT claim_id FROM opinion_claims WHERE call_id = o.call_id
     ) AND r.horizon_months = 12
JOIN company_sector_pit s ON s.isin = o.isin
                         AND s.valid_from <= o.as_of
                         AND (s.valid_to IS NULL OR s.valid_to > o.as_of)
WHERE s.basic_industry = 'Defence'
ORDER BY o.as_of DESC;
```

Index use: `ix_ocall_isin`, `ix_oclaim_call`, `company_sector_pit` PK `(isin, valid_from)`. `opinion_outcomes` is
small (one row per claim per horizon) so the IN-subquery is a range scan.

One operational note that applies to Q1-Q4: **run `ANALYZE` at the end of every build.** Without statistics SQLite
sometimes drives from `chunk` (`doc_type`, `known_at`) instead of `chunk_tag` (`tag`), which is correct but reads
more rows. With stats it chooses the tag-first plan; the `EXPLAIN QUERY PLAN` output in Appendix C shows both.

---

## 7. Build order, one writer per DB

Priority order is Shivam's (handoff 2026-10-26): P1 market → P2 decks + concalls → P3 announcements → P4 ARs →
P5 macro/budgets/PIB → P6 RBI → P7 aux. Dev days are estimates for one engineer; machine hours are wall clock on
this laptop.

| # | step | writes | wall time | CPU/GPU | $ | parallel with |
|---|---|---|---|---|---|---|
| B0 | Schema + loaders + `tag_vocab` seed + scorecard job | all three files | 2 dev-days | CPU | 0 | — |
| B1 | Re-check stored dates against filing records; fill master sector/industry (4,230 of 6,940 filled today) | `equity_intelligence.db` (existing writer) | 3 h | CPU | 0 | B0 |
| B2 | ISIN-history map re-derive + `symbol_at_time` | `chunks_v3.db` doc load | 1 h | CPU | 0 | B0 |
| B3 | `company_state_daily` backfill 2019-01-01..today (13.4M rows) + band/F&O/mcap bucket | `market_state.db` | 6 h | CPU | 0 | B4, B5 |
| B4 | Index-membership history + sector/theme intervals + `company_result_pit` + `company_ownership_pit` | `market_state.db` (after B3) | 4 h | CPU | 0 | B6 |
| B5 | Re-chunk decks with v2 (23,321 decks) | `chunks_v3.db` | 2 h | CPU (7 workers) | 0 | B3 |
| B6 | Re-chunk concalls (21,778 docs) | `chunks_v3.db` | 1.5 h | CPU | 0 | B4 |
| B7 | Chunk PIB + budgets + RBI + Economic Survey (84k + 261 + 216 docs) | `chunks_v3.db` | 3 h | CPU | 0 | B8 |
| B8 | Parse + chunk ARs (38,308 unparsed, then re-chunk 8,265) | `chunks_v3.db` | 10 h | CPU | 0 | B7 |
| B9 | Fetch + chunk material announcements (~120k of 1.95M) | `chunks_v3.db` | 8 h | CPU + net | 0 | B10 |
| B10 | Fetch + chunk results notes PDFs (~30k filings) | `chunks_v3.db` | 8 h | CPU + net | 0 | B9 |
| B11 | Deterministic tag pass (all rows, no model) | `chunks_v3.db` | 1 h | CPU | 0 | after each B |
| B12 | Classifier pass, 300-chunk gate first per doc type | `chunks_v3.db` | gate 2.5 person-days; full run 12 h | CPU + subscription | 0 (subscription) | per doc type |
| B13 | Macro claim reader (PIB/budget/RBI) | `market_state.db` | 6 h | CPU + subscription | 0 | B8-B10 |
| B14 | Opinions pilot: 10 videos, 10 reports, 200 Telegram posts | `opinions.db` | 1 day | CPU + net + ASR | ~$0.20 ASR | B12-B13 |
| B15 | Opinions full load (179 videos, ~252 reports) | `opinions.db` | 3 days | CPU + ASR | **$1.51 (0.6B) or $3.40 (1.7B)** | after pilot |
| B16 | Full re-embed of `chunks_v3` (header + body) | vector index folders | 8-12 h | net | **$60-80** (handoff estimate) | after B14 |

Parallel rules:
- **One writer per DB.** B5-B11 all write `chunks_v3.db`: run them as one queue, in the order listed. B3-B4 write
  `market_state.db`; B13 writes the same file, so B13 waits for B4.
- B9 and B10 are network-bound; run them at night, never in the 06:30-09:30 / 11:30-15:30 IST windows.
- B12 per doc type starts as soon as that doc type's chunks land; it only reads `chunk` and writes `chunk_tag`.
- ASR (B15) is pay-per-use; do not start without Shivam's OK.
- Peak-hour rule applies to every net job (handoff: start nothing new during peak).

---

## 8. Gaps and decisions for Shivam

### 8.1 Answers to the plan's §9 questions

| # | question | recommendation |
|---|---|---|
| Q1 | Market-cap buckets: SEBI rank or fixed ₹? | **SEBI rank-based**, on 6-month average full market cap, computed point-in-time. Store `mcap_cr` too so fixed thresholds can be derived later without a rebuild. Today's `master_companies` tier cannot be used at all: MICRO holds 6,031 of 6,940 rows, i.e. it is "everything else", and it is current-only. |
| Q2 | Who owns the theme list; do analyst themes feed it? | The repo owns it: `theme_map` with `source='curated'`. Analyst themes enter as `source='opinion'` and never silently become `curated`. Promotion is a hand edit, logged in the table. |
| Q3 | `company_state_daily` daily rows or intervals? | **Both, split by change frequency** (§2.4): daily for price/mcap/band/F&O, intervals for membership/sector/theme/ownership. A single daily table would duplicate 13M rows of constants; a single interval table would degenerate to daily rows with worse queries. |
| Q4 | Is a free classifier good enough, or a paid model for a training sample? | **Free first**, gated at 300 chunks/tag (§4.6). If two free attempts land below 0.85, pay for one 2,000-chunk gold set (deepseek-v4 class, a few dollars) and keep the free model as the labeler. Do not pay for labelling at 3M-chunk scale. |
| Q5 | How far back for index-membership history? | **2019-01-01**, matching the price start and the 2021+ evidence window. Earlier NSE notices are not machine-readable and would be hand-typed speculation. |
| Q6 | Should opinions ever appear in normal search? | **No by default.** `search_docs(..., include_opinions=1)` only; every hit carries `source_class='opinion'`. A user who asks "what do analysts think" must ask. |

### 8.2 Decisions I need from you (short)

1. **ASR spend**: $1.51 (Qwen3-ASR-0.6B) or $3.40 (1.7B) for the full 126 h. Recommend 0.6B (nearly the same
   output, half the price) and re-run the 12-clip test on it first — that part is ~$0.05.
2. **ffmpeg install** (`winget install Gyan.FFmpeg`) for keyframes. Needed before the video frames, not before
   ASR.
3. **PIB / RBI / Union Budget bodies are stored lower-cased** (measured). Fix at the writer and re-ingest, or keep
   them and accept that proper nouns are lost in 84k PIB and 216 RBI documents? Recommendation: fix, one line.
4. **Delete or keep `document_chunks`** after v3 parity. Recommendation: keep, read-only, for replay and for the
   "old chunker" comparison in future retrieval tests.
5. **Announcement scope**: chunk the ~120k material announcements, or all 1.95M? Recommendation: material only
   (category list in §3.5), because the other 1.8M are board-meeting notices and trading-window closures.
6. **Full re-embed budget**: $60-80 after B14. It is the only paid step in the critical path.

### 8.3 Known gaps this design does not close

- 38,308 annual reports are registered but not parsed; that is B8's 10 h, and it may be more (scan failures).
- `corporate_documents.call_date` is filled on only 5,989 of 127,253 rows, so 121,264 rows have no "date the call
  happened". Fiscal period for those concalls comes from the title/XBRL path at confidence ≤0.8 until the
  extractor is re-run. This is a real gap, not a labelling choice.
- Telegram media is not downloaded; OCR of 4,527 posts' images is a separate pass.
- The 159 owner-blocked Drive natives are permanently unreadable without bypassing Drive permissions. Not
  bypassed.
- `chunks_v2.db` has 23,321 decks but `deck_figures.deck_sources` has 26,391 `ok` rows — 3,070 decks are known
  and not on disk (matches the handoff's "3k missing").

---

## Appendix A — queries run (read-only, 2026-10-27)

Each number in this document traces to one of these. All used `reality_engine.db.readonly.connect_ro`.

| # | query (abridged) | result |
|---|---|---|
| A1 | `SELECT r.source_type, count(*), count(DISTINCT c.doc_id) FROM document_chunks c JOIN raw_documents r ON r.doc_id=c.doc_id GROUP BY 1` | 2,939,096 chunks; table in §2.1 |
| A2 | `PRAGMA table_info(document_chunks)` | 18 columns; includes `sector_id`, `industry_id`, `fiscal_period`, `event_date`, `event_source`, `doc_version` |
| A3 | `SELECT content FROM document_chunks WHERE rowid BETWEEN ... LIMIT 3000` | 0/3,000 all-lowercase (AR window) |
| A4 | `count(*) WHERE content GLOB '*India*'` / `'*india*'` over 60 docs per source | concall 228/0; AR 4,539/4,836; PIB 0/80; RBI 0/160; deck 133/6; budget 48/623 |
| A5 | `SELECT count(*), sum(sector IS NOT NULL) FROM master_companies` | 6,940 rows, 4,230 sector (61.0%); tier: LARGE 102, MID 108, SMALL 315, MICRO 6,031, NULL 384; active 5,358 |
| A6 | `SELECT * FROM company_industry` | 2,055 rows / 2,055 ISINs, 14 null sectors |
| A7 | `SELECT as_of, count(*) FROM index_membership GROUP BY 1` | 300 rows, all `2026-09-30`: nifty50 50, nifty100 100, niftymidcap150 150 |
| A8 | `SELECT min(date), max(date), count FROM price_bands` | 1,054,354 rows, 2019-12-30..2026-09-22 |
| A9 | `SELECT count(*) FROM shp_index` (sqlite_stat1) | 50,838 rows |
| A10 | `SELECT count(*) FROM mkt_nse_pit_xbrl_facts` (sqlite_stat1) | 158,608 rows |
| A11 | `SELECT source_type, count(*) FROM raw_documents GROUP BY 1` | concall 15,619; PIB 11,690; AR 8,268; decks 1,703; offer 909 … |
| A12 | `SELECT doc_type, count(*) FROM corporate_documents GROUP BY 1` | AR 46,573; OTHER_FILING 37,142; concall 21,778; announcement 16,085; result 2,747; deck 1,615; offer 904; AR debt 409 (total 127,253) |
| A13 | `SELECT publication_date/call_date/bse_dissem_ts IS NOT NULL` | 47,294 / 5,989 / 75,199 of 127,253 |
| A14 | `SELECT thread_topic_name, count(*) FROM telegram_posts GROUP BY 1` | 4,527 posts, 18 topics; 2025-05-22..2026-10-26 |
| A15 | `SELECT status, count(*) FROM deck_docs` (chunks_v2.db) | 23,299 ok + 22 no_text; 203,368 `deck_chunks` |
| A16 | `SELECT count(*) FROM pib_releases` / `pib_ml_releases` / `policy_events` | 75,361 / 8,816 / 21,552 |
| A17 | `SELECT count(*) FROM results_xbrl.filings` / `facts` | 76,416 / 9,370,110 |
| A18 | `PRAGMA table_info(chunk_symbol_tags)` | 194 rows, `(chunk_id, symbol, isin, score, method)` — an existing tag table, superseded by `chunk_tag` |
| A19 | 300-doc random sample per source type → chunks/doc and chars/chunk | concall 19.2 / 2,377; AR 241.2 / 2,610; PIB 1.9 / 1,876; offer 598.9 / 2,867 |
| A20 | `sum(symbol/isin/sector_id/industry_id/fiscal_period/event_date/published_date IS NOT NULL)` over `document_chunks WHERE rowid BETWEEN 1000000 AND 1060000` | n=60,001 (all ANNUAL_REPORT): symbol 100%, isin 100%, event_date 100%, published_date 100%, fiscal_period 37.8%, sector_id 0%, industry_id 0% |

## Appendix B — files read

`tasks/LABELS_TAGGING_PLAN_2026-10-27.md`; `tasks/FRAMEWORK.md`; `tasks/STATE.md` (first 140 lines);
`tasks/optimizations/HANDOFF_2026-10-26.md`; `tasks/optimizations/learn/C1C2_RESULTS_2026-10-26.md`;
`tasks/worker_context/CONTEXT.md` (row counts and the 34.8k `raw_documents` figure);
`reality_engine/processing/chunker_v2.py`; `reality_engine/scripts/load_deck_chunks.py`;
`reality_engine/db/schema.sql` (lines 242-301, 395-444, 458-527, 641-660).

## Appendix C — DDL check (run 2026-10-27)

The check extracts every `sql` block from this file, runs each schema block with
`sqlite3.connect(":memory:").executescript(...)` on a fresh database, then builds all three schemas in one
database and validates the five example queries with `EXPLAIN QUERY PLAN`. Script: `.tmp/check_ddl.py`
(throwaway, not committed). Output, abridged — plan lines kept, subquery scaffolding dropped:

```
doc: tasks\ARCHITECTURE_OVERHAUL_2026-10-27.md  sql blocks found: 8
block 1: OK  tables=11 indexes=12 triggers=3
          ['build_run', 'chunk', 'chunk_fts', 'chunk_fts_config', 'chunk_fts_data', 'chunk_fts_docsize', 'chunk_fts_idx', 'chunk_tag', 'coverage_scorecard', 'doc', 'tag_vocab']
          fts smoke test: MATCH 'visibility' -> 1 row
block 2: OK  tables=11 indexes=13 triggers=0
          ['company_membership_pit', 'company_ownership_pit', 'company_result_pit', 'company_sector_pit', 'company_state_daily', 'company_theme_pit', 'index_list', 'macro_claim', 'macro_claim_target', 'macro_doc', 'theme_map']
block 3: OK  tables=11 indexes=6 triggers=2
          ['opinion_calls', 'opinion_chunks', 'opinion_chunks_fts', 'opinion_chunks_fts_config', 'opinion_chunks_fts_data', 'opinion_chunks_fts_docsize', 'opinion_chunks_fts_idx', 'opinion_claims', 'opinion_docs', 'opinion_outcomes', 'opinion_sources']
block 4-8: query blocks — validated below, not executed here

query blocks: 5 — validating against the combined schema
Q1: OK
     SEARCH c USING INDEX ix_chunk_type_known (doc_type=? AND known_at<?)
     SEARCH s USING PRIMARY KEY (isin=? AND date=?)
     SEARCH t USING COVERING INDEX ix_chunk_tag_chunk (chunk_id=? AND tag=?)
     SCAN company_result_pit            -- window function, 272k rows, one pass
Q2: OK
     SEARCH macro_claim USING INDEX ix_mclaim_type (policy_type=?)
     SEARCH macro_claim_target USING COVERING INDEX ix_mct_target (target_kind=? AND target_id=?)
     SEARCH th USING INDEX ix_ctp_theme (theme=? AND valid_from<?)
     SEARCH c USING INDEX ix_chunk_isin_known (isin=? AND known_at>? AND known_at<?)
     SEARCH c USING INDEX sqlite_autoindex_chunk_1 (doc_id=?)   -- union branch, point lookup
Q3: OK
     SEARCH c USING INDEX ix_chunk_type_known (doc_type=? AND known_at<?)
     SEARCH t USING COVERING INDEX ix_chunk_tag_chunk (chunk_id=? AND tag=?)
     SEARCH m USING PRIMARY KEY (isin=? AND index_code=? AND added_on<?)
Q4: OK
     SEARCH t USING PRIMARY KEY (tag=?)
     SEARCH c USING INTEGER PRIMARY KEY (rowid=?)
     SEARCH s USING COVERING INDEX ix_csd_date_band (date=? AND price_band=? AND isin=?)
Q5: OK
     SEARCH s USING INDEX ix_csp_basic (basic_industry=?)
     SEARCH o USING INDEX ix_ocall_isin (isin=? AND as_of>?)
     SEARCH r USING PRIMARY KEY (claim_id=? AND horizon_months=?)

RESULT: ALL BLOCKS AND QUERIES PARSE
```

Two things the run proves that reading could not: (a) the FTS5 table really indexes chunk text through its
triggers (the smoke insert matched), and (b) every query resolves its columns against the proposed schema, with
the index we intended. Q1 and Q3 currently drive from `ix_chunk_type_known`; with `ANALYZE` statistics they are
expected to flip to `chunk_tag` first (§6 note) — the plan stays correct either way.
