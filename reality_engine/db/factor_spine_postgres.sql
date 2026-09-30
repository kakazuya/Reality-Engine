-- ====================================================================
-- FACTOR SPINE (PostgreSQL DDL)  -  additive only.
--
-- Parity translation of reality_engine/db/factor_spine_schema.sql.
-- Implementation of tasks/FACTOR_SPINE_DESIGN_2026-09-29.md section 1.2-section 1.8.
--
-- WHY A SEPARATE FILE: the live 33 GB database is SQLite; PostgreSQL is the
-- eventual production primary (AGENTS.md rule 2) but is not running. SQLite
-- has no exclusion constraints, no LATERAL, and (by default) enforces no
-- FKs, so the guarantees in the two engines differ measurably. This file
-- exists so the PG guarantee exists in one engine and is MEASURED in the
-- other, and so a future migration is a translation rather than a rewrite.
-- It is deliberately NOT appended to postgres_schema.sql by this task:
-- schema.sql / postgres_schema.sql are the shared live-schema files and are
-- out of scope for the spine work.
--
-- DELIBERATE DIFFERENCES from the SQLite DDL:
--   * TEXT 'YYYY-MM-DD' dates  -> DATE. The repo's additive SQLite tables
--     use TEXT dates (moat_history.asof_date, model_validation_scores),
--     so this is a divergence by engine, not by intent.
--   * INTEGER PRIMARY KEY AUTOINCREMENT -> BIGSERIAL.
--   * TEXT truthiness           -> BOOLEAN, with a CHECK that the value is
--     actually 0/1 so the SQLite-shaped loader cannot write garbage.
--   * NO exclusion constraints. The version chain's uniqueness guarantee
--     (one row per series/period/vintage) is a real UNIQUE constraint on
--     both engines; full bitemporality would need EXCLUDE USING gist and is
--     explicitly declined (design section 1.5, open question Q2).
--   * ivfflat is NOT applied: the spine is expected at <100k observation
--     rows (design section 1.5 point 3), far below where the index pays for
--     itself, and ivfflat requires trained centroids.
-- ====================================================================


-- --------------------------------------------------------------------
-- 1. factor_series  -  the DEFINITION of a series.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor_series (
    series_id BIGSERIAL PRIMARY KEY,
    factor_key TEXT NOT NULL UNIQUE,        -- stable public id: 'IN.RBI.REPO_RATE'
    display_name TEXT,
    family TEXT NOT NULL,                   -- rates_credit | crude_energy | policy_budget
                                            -- | fx_flows | metals | OTHER
    unit TEXT NOT NULL,                     -- 'pct' | 'inr_cr' | 'inr_tonne' | 'usd_inr' | 'index'
    frequency TEXT NOT NULL,                -- daily | weekly | monthly | quarterly
                                            -- | irregular (event-driven) | annual
    value_semantics TEXT NOT NULL DEFAULT 'level',
    source TEXT NOT NULL,                   -- rbi_official | mospi | pib | nse_official
                                            -- | vendor:<name> | manual | fixture
    source_url TEXT,
    methodology_notes TEXT,
    license TEXT,
    current_status TEXT NOT NULL DEFAULT 'active'
                    CHECK (current_status IN ('active','deprecated','unreachable')),
    -- read contract (declared once, enforced by the resolver)
    aggregation_policy TEXT NOT NULL DEFAULT 'lvcf'
                    CHECK (aggregation_policy IN ('lvcf','last','sum','none')),
    -- HARD staleness ceiling. NOT NULL is deliberate: a series may not
    -- claim "always fresh". Enforced in the resolver (design R6).
    max_lookback_days INTEGER NOT NULL CHECK (max_lookback_days >= 0),
    expected_publication_lag_days INTEGER NOT NULL DEFAULT 0
                    CHECK (expected_publication_lag_days >= 0),
    is_point_in_time INTEGER NOT NULL DEFAULT 1
                    CHECK (is_point_in_time IN (0,1)),
    availability_contract TEXT NOT NULL DEFAULT 'pita_strict'
                    CHECK (availability_contract IN ('pita_strict','pita_estimated')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fs_family ON factor_series(family, current_status);
CREATE INDEX IF NOT EXISTS idx_fs_source ON factor_series(source);


-- --------------------------------------------------------------------
-- 2. factor_observation  -  the FACT. as_of_date is the ONLY read gate.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor_observation (
    observation_id BIGSERIAL PRIMARY KEY,
    series_id BIGINT NOT NULL REFERENCES factor_series(series_id),
    period_start DATE NOT NULL,             -- inclusive first day of the MEASURED period
    period_end DATE NOT NULL,               -- inclusive last day of the MEASURED period
    value DOUBLE PRECISION,                 -- NULL is a legal, meaningful observation
    unit TEXT,
    as_of_date DATE NOT NULL,               -- KNOWLEDGE date. THE ONLY read gate.
    retrieved_at TIMESTAMPTZ NOT NULL,      -- system time. NEVER a read predicate.
    source TEXT NOT NULL,
    source_url TEXT,
    vintage INTEGER NOT NULL DEFAULT 1 CHECK (vintage >= 1),
    revision_of BIGINT REFERENCES factor_observation(observation_id),
    is_latest INTEGER NOT NULL DEFAULT 1 CHECK (is_latest IN (0,1)),
                                      -- DISPLAY/AUDIT ONLY. Never a read predicate.
    confidence DOUBLE PRECISION CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    notes TEXT,
    source_doc_id BIGINT,                  -- -> raw_documents.doc_id
    chunk_span TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_fo_series_period_vintage
        UNIQUE (series_id, period_start, period_end, vintage)
);
-- THE hot path. Column order mirrors the resolver's ORDER BY exactly.
CREATE INDEX IF NOT EXISTS idx_fo_series_asof
    ON factor_observation(series_id, as_of_date DESC, period_end DESC, is_latest);
CREATE INDEX IF NOT EXISTS idx_fo_series_period
    ON factor_observation(series_id, period_end DESC);
CREATE INDEX IF NOT EXISTS idx_fo_source_retrieved
    ON factor_observation(source, retrieved_at DESC);
CREATE INDEX IF NOT EXISTS idx_fo_period_start
    ON factor_observation(series_id, period_start DESC);
CREATE INDEX IF NOT EXISTS idx_fo_latest_only
    ON factor_observation(series_id, period_start, period_end)
    WHERE is_latest = 1;


-- --------------------------------------------------------------------
-- 3. factor_event_window  -  a SHOCK with an effect window. Decay is
--    computed at QUERY time from pruning_decay_config, never stored.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor_event_window (
    event_window_id BIGSERIAL PRIMARY KEY,
    series_id BIGINT NOT NULL REFERENCES factor_series(series_id),
    macro_event_id TEXT,                   -- soft link -> macro_events.event_id (TEXT)
    event_label TEXT NOT NULL,
    announced_date DATE NOT NULL,
    window_start DATE NOT NULL,
    window_end DATE,
    magnitude DOUBLE PRECISION,             -- NULL if not yet quantified (honest-NULL)
    direction SMALLINT CHECK (direction IS NULL OR direction IN (-1,1)),
    lag_time_months INTEGER,
    probability DOUBLE PRECISION CHECK (probability IS NULL OR (probability >= 0 AND probability <= 1)),
    as_of_date DATE NOT NULL,               -- knowledge date of THIS magnitude
    vintage INTEGER NOT NULL DEFAULT 1 CHECK (vintage >= 1),
    is_latest INTEGER NOT NULL DEFAULT 1 CHECK (is_latest IN (0,1)),
    confidence DOUBLE PRECISION,
    source TEXT NOT NULL,
    source_url TEXT,
    source_doc_id BIGINT,
    chunk_span TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_few_series_label_announced_vintage
        UNIQUE (series_id, event_label, announced_date, vintage),
    CONSTRAINT ck_few_window_order CHECK (window_end IS NULL OR window_end >= window_start)
);
CREATE INDEX IF NOT EXISTS idx_few_series_date ON factor_event_window(series_id, announced_date DESC);
CREATE INDEX IF NOT EXISTS idx_few_macro_event ON factor_event_window(macro_event_id);


-- --------------------------------------------------------------------
-- 4. factor_symbol_link  -  SPECIFIED BUT NOT POPULATED.
--    Ships empty and stays empty until the exposure-edge estimation step
--    exists (design section 3.4 items 1-2). No code writes to it.
--    Keyed on `symbol` TEXT, NOT on an integer company_id FK: the numeric
--    company_id FKs elsewhere in this schema are surrogate ids from a
--    `companies` table that has no SQLite counterpart and resolve 0/2,653
--    against master_companies in the live data.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor_symbol_link (
    link_id BIGSERIAL PRIMARY KEY,
    series_id BIGINT NOT NULL REFERENCES factor_series(series_id),
    symbol TEXT NOT NULL,                  -- the ONLY company key that resolves today
    isin TEXT,                             -- copied, NOT a join key
    exposure_magnitude DOUBLE PRECISION,    -- d(return)/d(factor). NULL = not estimated
    exposure_direction SMALLINT CHECK (exposure_direction IS NULL OR exposure_direction IN (-1,1)),
    exposure_basis TEXT,                   -- declared_segment | revenue_mix
                                           -- | estimated_panel | llm_distilled
    as_of_date DATE NOT NULL,
    vintage INTEGER NOT NULL DEFAULT 1 CHECK (vintage >= 1),
    is_latest INTEGER NOT NULL DEFAULT 1 CHECK (is_latest IN (0,1)),
    confidence DOUBLE PRECISION,
    source TEXT NOT NULL,
    source_doc_id BIGINT,
    chunk_span TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_fsl_series_symbol_asof_vintage
        UNIQUE (series_id, symbol, as_of_date, vintage)
);
CREATE INDEX IF NOT EXISTS idx_fsl_symbol ON factor_symbol_link(symbol, series_id);
CREATE INDEX IF NOT EXISTS idx_fsl_series ON factor_symbol_link(series_id, as_of_date DESC);


-- --------------------------------------------------------------------
-- 5. factor_load_run  -  the "it tried and this is what happened" audit.
--    DDL only; the loader is a separate task.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor_load_run (
    load_run_id BIGSERIAL PRIMARY KEY,
    series_id BIGINT,
    factor_key TEXT,
    status TEXT NOT NULL CHECK (status IN ('ok','partial','failed','refused')),
    n_observations INTEGER DEFAULT 0,
    n_inserted INTEGER DEFAULT 0,
    n_revised INTEGER DEFAULT 0,
    earliest_period_end DATE,
    latest_period_end DATE,
    latest_as_of_date DATE,
    source TEXT,
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_flr_series ON factor_load_run(series_id, load_run_id DESC);
