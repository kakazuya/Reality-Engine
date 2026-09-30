-- ====================================================================
-- FACTOR SPINE (SQLite fallback DDL)  -  additive only.
--
-- Implementation of tasks/FACTOR_SPINE_DESIGN_2026-09-29.md section 1.2-section 1.8.
-- Owned by reality_engine/processing/factor_spine.py, which ships the
-- idempotent ensure_factor_spine_schema() helper (precedent:
-- substrate_hygiene.ensure_schema, move_attributor.ensure_move_attribution_schema,
-- Repository.ensure_validation_schema at repository.py:3853).
--
-- THE LIVE DB IS AHEAD OF schema.sql. Editing schema.sql alone creates
-- nothing in reality_engine/data/equity_intelligence.db; this file is
-- executed by the ensure_* helper (or by the same DDL string embedded in
-- the owning module) and may later be APPENDED to schema.sql as
-- documentation. It must never be used to MODIFY an existing table.
--
-- PostgreSQL parity: reality_engine/db/factor_spine_postgres.sql.
--
-- RULES ENCODED HERE (design section 2.2, each rule is a test):
--   R1  as_of_date <= T is the ONLY visibility gate.
--   R2  period_end is never a visibility gate.
--   R3  retrieved_at is never a visibility gate (backfilled rows all carry
--       today's retrieval date; only as_of_date can answer "could we have
--       known this?").
--   R5  is_latest is DISPLAY/AUDIT ONLY  -  never a read predicate.
--   R6  age_days = julianday(T) - julianday(period_end) > max_lookback_days
--       means the value is NOT usable; the honest answer is NULL.
--   R7  never interpolate, never forward-fill a gap the ceiling does not cover.
--   R9  quarantine the SERIES and refuse; never fall back to a prior value.
--   R10 exactly one row out, always  -  even for an unknown series.
--
-- FOREIGN KEY clauses below are DOCUMENTATION for PG parity. SQLite runs
-- with PRAGMA foreign_keys = ON via SQLITE_PRAGMAS in some paths and OFF
-- in others, so the resolver treats a dangling series_id as a null gate
-- rather than trusting the constraint. Enforce in application code.
-- ====================================================================


-- --------------------------------------------------------------------
-- 1. factor_series  -  the DEFINITION of a series (what it measures and
--    how it may be read). Registered from a code constant, never from a
--    fetch, so the schema is useful before any network call succeeds.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor_series (
    series_id INTEGER PRIMARY KEY AUTOINCREMENT,
    factor_key TEXT NOT NULL UNIQUE,        -- stable public id: 'IN.RBI.REPO_RATE'
    display_name TEXT,
    family TEXT NOT NULL,                   -- rates_credit | crude_energy | policy_budget
                                            -- | fx_flows | metals | OTHER (design section 1.3)
    unit TEXT NOT NULL,                     -- 'pct' | 'inr_cr' | 'inr_tonne' | 'usd_inr' | 'index'
    frequency TEXT NOT NULL,                -- daily | weekly | monthly | quarterly
                                            -- | irregular (event-driven) | annual
    value_semantics TEXT NOT NULL DEFAULT 'level',
                                            -- level | rate | index_level | spread
    source TEXT NOT NULL,                   -- rbi_official | mospi | pib | nse_official
                                            -- | vendor:<name> | manual | fixture
    source_url TEXT,                        -- canonical landing page for the series
    methodology_notes TEXT,                 -- how the number is defined/derived
    license TEXT,                           -- redistribution terms (design section 6 Q5)
    current_status TEXT NOT NULL DEFAULT 'active',
                                            -- active | deprecated | unreachable
    -- ---- read contract (declared once, enforced by the resolver) ----
    aggregation_policy TEXT NOT NULL DEFAULT 'lvcf',
                                            -- lvcf  : step/level, carry last value forward
                                            -- last  : flow/period value, take the period
                                            -- sum   : accumulate within a window
                                            -- none  : point observation, never carried
                                            --        (declare max_lookback_days=0 so the
                                            --         staleness ceiling, not a special
                                            --         case, is what stops the carry)
    max_lookback_days INTEGER NOT NULL,     -- HARD staleness ceiling. NOT NULL is
                                            -- deliberate: a series may not claim
                                            -- "always fresh". This is the single most
                                            -- important column in the table (design section 1.2).
    expected_publication_lag_days INTEGER NOT NULL DEFAULT 0,
                                            -- flow series: ref period end -> publication.
                                            -- Used by the load audit, NEVER by the resolver.
    is_point_in_time INTEGER NOT NULL DEFAULT 1,
                                            -- 1 : as_of_date is the publisher's stated date
                                            -- 0 : as_of_date is OUR reconstruction; usable
                                            --     but must be reported alongside every answer
    availability_contract TEXT NOT NULL DEFAULT 'pita_strict',
                                            -- pita_strict | pita_estimated
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fs_family ON factor_series(family, current_status);
CREATE INDEX IF NOT EXISTS idx_fs_source ON factor_series(source);


-- --------------------------------------------------------------------
-- 2. factor_observation  -  the FACT (a number attached to a measured
--    period, with the date on which it became public).
--
--    Kinds (a) step function, (b) flow with publication lag and
--    (d) revision all live here: they are the same storage fact and
--    differ only in read semantics, which is a property of the SERIES
--    definition, not of the row. See design section 1.4 for why.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor_observation (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER NOT NULL,
    period_start TEXT NOT NULL,        -- inclusive first day of the MEASURED period
    period_end TEXT NOT NULL,          -- inclusive last day of the MEASURED period
                                      -- (== period_start for a point/step observation)
    value REAL,                        -- NULL is a legal, meaningful observation
    unit TEXT,                         -- snapshot of series.unit at observation time
    as_of_date TEXT NOT NULL,          -- KNOWLEDGE date: earliest date this number was
                                      -- PUBLIC. THE ONLY temporal gate in any read.
    retrieved_at TEXT NOT NULL,        -- when WE fetched it (system time). NEVER a
                                      -- read predicate. A backfill legitimately
                                      -- stamps today on every historical row.
    source TEXT NOT NULL,
    source_url TEXT,
    vintage INTEGER NOT NULL DEFAULT 1,-- 1 = first release; 2.. = restatements (design section 1.5)
    revision_of INTEGER,               -- observation_id of the vintage this supersedes
    is_latest INTEGER NOT NULL DEFAULT 1,
                                      -- DISPLAY/AUDIT ONLY. "Latest as of NOW", which is
                                      -- precisely a look-ahead. The resolver MUST NOT
                                      -- filter on this (design R5).
    confidence REAL,                   -- 0..1; loader-set, never model-set
    notes TEXT,
    -- provenance (strategies.md section 1: symbol + fiscal + event_date +
    --             source_doc_id + chunk_span)
    source_doc_id INTEGER,             -- -> raw_documents.doc_id when extracted from a
                                      -- stored document. NULL for pure web/API pulls.
    chunk_span TEXT,                   -- 'chunk_id:start_off-end_off'
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (series_id) REFERENCES factor_series(series_id),
    UNIQUE(series_id, period_start, period_end, vintage)
);

-- THE hot path: "latest vintage of the latest period known on date T, for
-- series S". Column order mirrors the resolver's ORDER BY exactly.
CREATE INDEX IF NOT EXISTS idx_fo_series_asof
    ON factor_observation(series_id, as_of_date DESC, period_end DESC, is_latest);
-- Window scans (deltas, returns, panel regression inputs).
CREATE INDEX IF NOT EXISTS idx_fo_series_period
    ON factor_observation(series_id, period_end DESC);
-- Freshness / load audit: which series have gone quiet.
CREATE INDEX IF NOT EXISTS idx_fo_source_retrieved
    ON factor_observation(source, retrieved_at DESC);
-- Provisional-provenance surfacing (is_point_in_time=0 series get a loud label).
CREATE INDEX IF NOT EXISTS idx_fo_period_start
    ON factor_observation(series_id, period_start DESC);
-- Version-chain integrity probe (partial index, SQLite >= 3.8.0).
CREATE INDEX IF NOT EXISTS idx_fo_latest_only
    ON factor_observation(series_id, period_start, period_end)
    WHERE is_latest = 1;


-- --------------------------------------------------------------------
-- 3. factor_event_window  -  kind (c): a SHOCK with an effect window.
--    Deliberately NOT a factor_observation row. Forcing it into one would
--    mean NULL-able window_end/magnitude/direction on 100% of rows and
--    would invite aggregation_policy='lvcf' to carry an EVENT magnitude
--    forward as if it were a level (design section 1.4).
--
--    Magnitudes decay. The decayed value is computed at QUERY time from
--    pruning_decay_config, never stored: a stored decayed number silently
--    disagrees with the config the moment someone tunes a half-life.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor_event_window (
    event_window_id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER NOT NULL,           -- the SHOCK series, e.g. IN.BUDGET.RAIL_CAPEX
    macro_event_id TEXT,                  -- soft link -> macro_events.event_id (TEXT)
    event_label TEXT NOT NULL,            -- human: 'FY26 Rail Capex provision'
    announced_date TEXT NOT NULL,         -- public announcement (== as_of for the shock)
    window_start TEXT NOT NULL,           -- effect begins
    window_end TEXT,                      -- effect ends; NULL = open-ended
    magnitude REAL,                       -- in series.unit; NULL if not yet quantified
    direction INTEGER,                    -- +1 tailwind | -1 headwind | NULL unknown
    lag_time_months INTEGER,              -- consistent with ripple_effects.lag_time_months
    probability REAL,                     -- 0..1, honest-NULL if unquantified
    as_of_date TEXT NOT NULL,             -- knowledge date of THIS magnitude (may be revised)
    vintage INTEGER NOT NULL DEFAULT 1,
    is_latest INTEGER NOT NULL DEFAULT 1,
    confidence REAL,
    source TEXT NOT NULL,
    source_url TEXT,
    source_doc_id INTEGER,
    chunk_span TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (series_id) REFERENCES factor_series(series_id),
    UNIQUE(series_id, event_label, announced_date, vintage)
);
CREATE INDEX IF NOT EXISTS idx_few_series_date ON factor_event_window(series_id, announced_date DESC);
CREATE INDEX IF NOT EXISTS idx_few_macro_event ON factor_event_window(macro_event_id);


-- --------------------------------------------------------------------
-- 4. factor_symbol_link  -  SPECIFIED BUT NOT POPULATED.
--    *** This table ships empty and stays empty until the exposure-edge
--    *** estimation step exists (design section 3.4 item 1). Nothing in the repo
--    *** can currently produce a defensible exposure_magnitude, and an
--    *** asserted exposure is "a placeholder wearing a number's clothes"
--    *** (design section 3.4 item 2). The table exists so the schema is not
--    *** retrofitted, and so "which series COULD apply to which names" is
--    *** answerable before "by how much" is.
--    *** Nothing writes to it: no function in factor_spine.py inserts here.
--    ***
--    *** It keys on `symbol` TEXT and declares NO integer company_id FK:
--    ***    integer company_id FKs into master_companies are dangling
--    ***    (0/2,653 on moat_evaluations, 0 on business_model_profiles).
--    ***    symbol/ticker TEXT is the only key that resolves today.
--    ***    `isin` is copied for display, never used as a join key.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor_symbol_link (
    link_id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,                  -- the ONLY company key that resolves today
    isin TEXT,                             -- copied, NOT a join key
    exposure_magnitude REAL,               -- d(return)/d(factor). NULL = not yet estimated
    exposure_direction INTEGER,            -- +1 | -1 | NULL
    exposure_basis TEXT,                   -- 'declared_segment' | 'revenue_mix' |
                                          -- | 'estimated_panel' | 'llm_distilled'
    as_of_date TEXT NOT NULL,              -- when this exposure was KNOWN
    vintage INTEGER NOT NULL DEFAULT 1,
    is_latest INTEGER NOT NULL DEFAULT 1,
    confidence REAL,
    source TEXT NOT NULL,
    source_doc_id INTEGER,
    chunk_span TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (series_id) REFERENCES factor_series(series_id),
    UNIQUE(series_id, symbol, as_of_date, vintage)
);
CREATE INDEX IF NOT EXISTS idx_fsl_symbol ON factor_symbol_link(symbol, series_id);
CREATE INDEX IF NOT EXISTS idx_fsl_series ON factor_symbol_link(series_id, as_of_date DESC);


-- --------------------------------------------------------------------
-- 5. factor_load_run  -  the "it tried and this is what happened" audit.
--    DDL only. The loader and the audit writer are NOT in this task
--    (design section 4.2); a loader that cannot reach its source records a
--    'failed' row here and returns [] rather than raising into the
--    pipeline.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor_load_run (
    load_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER,
    factor_key TEXT,
    status TEXT NOT NULL,              -- ok | partial | failed | refused
    n_observations INTEGER DEFAULT 0,
    n_inserted INTEGER DEFAULT 0,
    n_revised INTEGER DEFAULT 0,
    earliest_period_end TEXT,
    latest_period_end TEXT,
    latest_as_of_date TEXT,
    source TEXT,
    error TEXT,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_flr_series ON factor_load_run(series_id, load_run_id DESC);
