-- Fundamental Reality Engine â€” PostgreSQL + pgvector DDL

-- Combines Architecture PDFs: Moat/ENI/Ripple quantification + Multimodal ingestion

-- Migration target: replaces SQLite WAL for dense-substrate all-peers ensemble with continuous self-correction; SQLite WAL retained as local fallback



CREATE EXTENSION IF NOT EXISTS vector;



-- 1. Master Structural Hierarchy (Top-Down)

CREATE TABLE countries (

 country_id VARCHAR(3) PRIMARY KEY, -- ISO 3166-1 alpha-3

 country_name VARCHAR(100) NOT NULL,

 political_stability_score NUMERIC(3,2) CHECK (political_stability_score BETWEEN 1 AND 5),

 rule_of_law_index NUMERIC(3,2) CHECK (rule_of_law_index BETWEEN 1 AND 5),

 currency VARCHAR(10)

);



CREATE TABLE industries (

 industry_id SERIAL PRIMARY KEY,

 sector_name VARCHAR(100) NOT NULL,

 industry_name VARCHAR(100) NOT NULL UNIQUE,

 secular_growth_score NUMERIC(3,2) CHECK (secular_growth_score BETWEEN 1 AND 5),

 lifecycle_stage VARCHAR(30) CHECK (lifecycle_stage IN ('Early Adoption','Growth','Mature','Consolidating','Declining')),

 tam_growth_cagr NUMERIC(5,2)

);



CREATE TABLE companies (

 company_id SERIAL PRIMARY KEY,

 industry_id INT REFERENCES industries(industry_id),

 ticker VARCHAR(20) UNIQUE NOT NULL,

 company_name VARCHAR(255) NOT NULL,

 market_cap NUMERIC(18,2),

 isin VARCHAR(12) UNIQUE,

 reporting_currency VARCHAR(10) DEFAULT 'INR'

);



-- 2. Primary Qualitative Filter: Business Model & Moat

CREATE TABLE business_model_profiles (

 company_id INT PRIMARY KEY REFERENCES companies(company_id),

 archetype VARCHAR(50) CHECK (archetype IN ('Platform','Tollbooth','Subscription SaaS','Asset-Heavy OEM','Asset-Light OEM','Network','Marketplace','Commodity')),

 revenue_recurrence_pct NUMERIC(5,2) CHECK (revenue_recurrence_pct BETWEEN 0 AND 100),

 pricing_power_score INT CHECK (pricing_power_score BETWEEN 1 AND 5),

 capital_intensity_score INT CHECK (capital_intensity_score BETWEEN 1 AND 5),

 operating_leverage_score INT CHECK (operating_leverage_score BETWEEN 1 AND 5),

 qualitative_notes TEXT

);



CREATE TABLE moat_evaluations (

 company_id INT PRIMARY KEY REFERENCES companies(company_id),

 eval_date DATE DEFAULT CURRENT_DATE,

 switching_costs INT CHECK (switching_costs BETWEEN 0 AND 5),

 network_effects INT CHECK (network_effects BETWEEN 0 AND 5),

 cost_advantage INT CHECK (cost_advantage BETWEEN 0 AND 5),

 intangible_assets INT CHECK (intangible_assets BETWEEN 0 AND 5),

 efficient_scale INT CHECK (efficient_scale BETWEEN 0 AND 5),

 total_moat_score NUMERIC(4,2) GENERATED ALWAYS AS (

   (switching_costs * 0.25) + (network_effects * 0.25) + (cost_advantage * 0.20) + (intangible_assets * 0.20) + (efficient_scale * 0.10)

 ) STORED,

 moat_width VARCHAR(10) CHECK (moat_width IN ('None','Narrow','Wide')) GENERATED ALWAYS AS (

   CASE WHEN ((switching_costs * 0.25)+(network_effects*0.25)+(cost_advantage*0.20)+(intangible_assets*0.20)+(efficient_scale*0.10)) >= 3.5 THEN 'Wide' WHEN ((switching_costs*0.25)+(network_effects*0.25)+(cost_advantage*0.20)+(intangible_assets*0.20)+(efficient_scale*0.10)) >= 2.5 THEN 'Narrow' ELSE 'None' END

 ) STORED,

 moat_trajectory VARCHAR(15) CHECK (moat_trajectory IN ('Deteriorating','Stable','Expanding'))

);



-- 3. Geographic & Policy Exposure

CREATE TABLE geographic_exposure (

 company_id INT REFERENCES companies(company_id),

 country_id VARCHAR(3) REFERENCES countries(country_id),

 revenue_share_pct NUMERIC(5,2) CHECK (revenue_share_pct BETWEEN 0 AND 100),

 asset_exposure_pct NUMERIC(5,2) CHECK (asset_exposure_pct BETWEEN 0 AND 100),

 PRIMARY KEY (company_id, country_id)

);



CREATE TABLE regulatory_political_risks (

 risk_id SERIAL PRIMARY KEY,

 company_id INT REFERENCES companies(company_id),

 ticker VARCHAR(20),

 isin VARCHAR(12),

 symbol VARCHAR(20),

 policy_name VARCHAR(255) NOT NULL,

 risk_type VARCHAR(20) CHECK (risk_type IN ('Tailwind','Headwind','Auxiliary')),

 factor_type VARCHAR(30), -- Subsidy, Tariff, Antitrust, Environmental, FX

 severity_score NUMERIC(3,1) CHECK (severity_score BETWEEN -5.0 AND 5.0),

 probability NUMERIC(3,2) CHECK (probability BETWEEN 0.00 AND 1.00),

 net_impact_score NUMERIC(4,2) GENERATED ALWAYS AS (severity_score * probability) STORED, -- ENI

 time_horizon VARCHAR(20) CHECK (time_horizon IN ('Short-term','Mid-term','Structural')),

 coverage_status VARCHAR(20) CHECK (coverage_status IN ('mapped','no_template','unknown')) DEFAULT 'mapped',

 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  UNIQUE(symbol, policy_name)

);

-- Migration for existing PG clusters that were created before coverage_status/symbol columns (idempotent)
ALTER TABLE regulatory_political_risks ADD COLUMN IF NOT EXISTS ticker VARCHAR(20);
ALTER TABLE regulatory_political_risks ADD COLUMN IF NOT EXISTS isin VARCHAR(12);
ALTER TABLE regulatory_political_risks ADD COLUMN IF NOT EXISTS symbol VARCHAR(20);
ALTER TABLE regulatory_political_risks ADD COLUMN IF NOT EXISTS coverage_status VARCHAR(20) CHECK (coverage_status IN ('mapped','no_template','unknown')) DEFAULT 'mapped';
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='regulatory_political_risks_symbol_policy_name_key') THEN ALTER TABLE regulatory_political_risks ADD CONSTRAINT regulatory_political_risks_symbol_policy_name_key UNIQUE(symbol, policy_name); END IF; END $$;
CREATE INDEX IF NOT EXISTS idx_regpol_coverage ON regulatory_political_risks(coverage_status);
CREATE INDEX IF NOT EXISTS idx_regpol_symbol ON regulatory_political_risks(symbol);

-- 4. Multimodal Ingestion: Raw Documents + pgvector Chunks

CREATE TABLE raw_documents (

 doc_id SERIAL PRIMARY KEY,

 title VARCHAR(255) NOT NULL,

  source_type VARCHAR(50) NOT NULL, -- Union_Budget, Economic_Survey, State_Budget_UP, State_Budget_Tamil_Nadu, State_Budget_Maharashtra, State_Budget_Karnataka, State_Budget_Telangana, State_Budget_Gujarat, State_Budget_Haryana, State_Budget_Andhra_Pradesh, PIB_Circular, RBI_Annual_Report, RBI_Financial_Stability_Report, RBI_MPC, Earnings_Concall, YouTube_Analysis

 published_date DATE NOT NULL,

 fiscal_period VARCHAR(20), -- FY2026-27

 source_url TEXT,

 creator_or_ministry VARCHAR(100),

 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

);



CREATE TABLE document_chunks (

 chunk_id SERIAL PRIMARY KEY,

 doc_id INT REFERENCES raw_documents(doc_id) ON DELETE CASCADE,

 chunk_index INT NOT NULL,

 content TEXT NOT NULL,

 embedding VECTOR(1536),

 timestamp_start_sec INT, -- audio/video diarization

 timestamp_end_sec INT,

 sector_id INT,

 industry_id INT REFERENCES industries(industry_id),

 UNIQUE(doc_id, chunk_index)

);

CREATE INDEX ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);



-- 5. Causal Ripple DAG (Self-Referencing)

CREATE TABLE macro_events (

 event_id SERIAL PRIMARY KEY,

 doc_id INT REFERENCES raw_documents(doc_id),

 event_name VARCHAR(255) NOT NULL, -- e.g., Customs Duty Hike Steel

 event_category VARCHAR(50) CHECK (event_category IN ('Fiscal','Monetary','Regulatory','Geopolitical','Trade')),

 announcement_date DATE NOT NULL

);



CREATE TABLE ripple_effects (

 ripple_id SERIAL PRIMARY KEY,

 event_id INT NOT NULL REFERENCES macro_events(event_id) ON DELETE CASCADE,

 parent_ripple_id INT REFERENCES ripple_effects(ripple_id),

 order_level INT NOT NULL CHECK (order_level >= 1),

 target_type VARCHAR(20) CHECK (target_type IN ('Macro_Variable','Sector','Industry','Company')),

 target_sector_id INT,

 target_industry_id INT REFERENCES industries(industry_id),

 target_company_id INT REFERENCES companies(company_id),

 transmission_channel TEXT NOT NULL,

 transmission_elasticity NUMERIC(4,2) DEFAULT 1.0, -- -2.0 to 2.0

 raw_magnitude NUMERIC(3,1) CHECK (raw_magnitude BETWEEN -5.0 AND 5.0),

 probability NUMERIC(3,2) CHECK (probability BETWEEN 0.00 AND 1.00),

 lag_time_months INT DEFAULT 0,

 significance_rank NUMERIC(5,2) -- computed via recursive CTE: |MN|*20/(1+ln(1+Lag))

);

CREATE INDEX idx_ripple_hierarchy ON ripple_effects (event_id, parent_ripple_id, order_level);

CREATE INDEX idx_ripple_targets ON ripple_effects (target_company_id, target_industry_id);



-- 6. Secondary Financial Validation (peer-adjusted)

CREATE TABLE financial_metrics (

 company_id INT REFERENCES companies(company_id),

 fiscal_year INT,

 roic NUMERIC(6,3),

 wacc NUMERIC(6,3),

 roic_wacc_spread NUMERIC(6,3) GENERATED ALWAYS AS (roic - wacc) STORED,

 fcf_margin NUMERIC(6,3),

 debt_to_ebitda NUMERIC(6,2),

 gross_margin_peer_percentile INT,

 PRIMARY KEY (company_id, fiscal_year)

);

CREATE INDEX idx_fin_roic_spread ON financial_metrics (roic_wacc_spread);



-- 7. Quantification Verification Views

CREATE OR REPLACE VIEW v_wide_moat_candidates AS

SELECT c.ticker, c.company_name, m.total_moat_score, m.moat_width, m.moat_trajectory, b.pricing_power_score

FROM companies c

JOIN moat_evaluations m ON c.company_id=m.company_id

JOIN business_model_profiles b ON c.company_id=b.company_id

WHERE m.total_moat_score >= 3.5 AND m.moat_trajectory IN ('Stable','Expanding');



CREATE OR REPLACE VIEW v_policy_adjusted_screen AS

WITH pa AS (
  SELECT company_id,
         SUM(net_impact_score) AS agg_policy,
         COUNT(*) FILTER (WHERE policy_name != '__NO_POLICY_TEMPLATE__' AND (coverage_status='mapped' OR coverage_status IS NULL) AND net_impact_score IS NOT NULL) AS mapped_cnt
  FROM regulatory_political_risks
  WHERE policy_name != '__NO_POLICY_TEMPLATE__' AND (coverage_status='mapped' OR coverage_status IS NULL) AND net_impact_score IS NOT NULL
  GROUP BY company_id
)

SELECT c.ticker, m.total_moat_score, pa.agg_policy AS net_policy_score, f.roic_wacc_spread

FROM companies c

JOIN moat_evaluations m ON c.company_id=m.company_id

JOIN pa ON c.company_id=pa.company_id

JOIN financial_metrics f ON c.company_id=f.company_id

WHERE f.fiscal_year=2025 AND f.roic_wacc_spread > 0.05 AND pa.agg_policy >= 0;

-- Patch to postgres_schema.sql for 4-pillar pruning + visual alpha

-- Append after existing DDL



-- 7. Data Lifecycle & Retention (Pillar 1: Tiering)

-- Hot tier: last 12 months embeddings retained, Warm: 12-36m text only, Cold: >36m parquet export

-- Enforced via prune_decayed_signals() below



-- 8. Partition document_chunks by published_date (Pillar 3A) â€” alternative declarative partition

-- Note: replaces non-partitioned document_chunks if fresh install. For migration, recreate:

-- DROP TABLE document_chunks; then use partitioned DDL below. SQLite fallback keeps non-partitioned.



-- Partitioned variant (use for new PG clusters)

-- CREATE TABLE document_chunks (

--     chunk_id BIGSERIAL,

--     doc_id INT NOT NULL REFERENCES raw_documents(doc_id) ON DELETE CASCADE,

--     chunk_index INT NOT NULL,

--     content TEXT NOT NULL,

--     embedding VECTOR(1536),

--     published_date DATE NOT NULL,

--     timestamp_start_sec INT,

--     timestamp_end_sec INT,

--     sector_id INT,

--     industry_id INT REFERENCES industries(industry_id),

--     PRIMARY KEY (chunk_id, published_date)

-- ) PARTITION BY RANGE (published_date);

-- CREATE TABLE document_chunks_2026_q1 PARTITION OF document_chunks FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');

-- CREATE TABLE document_chunks_2026_q2 PARTITION OF document_chunks FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');

-- CREATE TABLE document_chunks_2026_q3 PARTITION OF document_chunks FOR VALUES FROM ('2026-07-01') TO ('2026-10-01');

-- CREATE TABLE document_chunks_2026_q4 PARTITION OF document_chunks FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');

-- CREATE INDEX ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);

-- Automated partition creation via pg_partman or cron.



-- 9. Decay & Graph Pruning Constants (Pillar 2)

CREATE TABLE pruning_decay_config (

 category VARCHAR(50) PRIMARY KEY, -- Analyst Commentary / YouTube, Concall/MPC, Budget/Tax Reform

 half_life_months NUMERIC(4,2) NOT NULL,

 lambda NUMERIC(6,4) GENERATED ALWAYS AS (LN(2) / half_life_months) STORED,

 significance_floor NUMERIC(4,2) DEFAULT 5.0,

 prob_cutoff NUMERIC(3,2) DEFAULT 0.08

);

INSERT INTO pruning_decay_config (category, half_life_months) VALUES

 ('Analyst Commentary / YouTube', 3),

 ('Quarterly Concall / MPC Stance', 6),

 ('Union Budget / Tax Reform', 12),

 ('State Budget', 12),

 ('PIB Circular', 3),

 ('RBI Report / Economic Survey', 6),

 ('Economic Survey', 12)

ON CONFLICT DO NOTHING;



-- 10. Visual Evidence Artifacts (Pillar: Multimodal Vision)

CREATE TABLE visual_evidence_artifacts (

 artifact_id SERIAL PRIMARY KEY,

 doc_id INT REFERENCES raw_documents(doc_id) ON DELETE CASCADE,

 chunk_id INT REFERENCES document_chunks(chunk_id) ON DELETE SET NULL,

 timestamp_start_sec INT NOT NULL,

 timestamp_end_sec INT,

 artifact_type VARCHAR(50) CHECK (artifact_type IN ('Financial_Table_Slide','Value_Chain_Diagram','Factory_Floor_Tour','Product_Tear_Down','CapEx_Timeline_Roadmap')),

 extracted_visual_data JSONB,

 visual_description TEXT NOT NULL,

 moat_implication TEXT,

 frame_snapshot_url TEXT,

 confidence_score NUMERIC(3,2) CHECK (confidence_score BETWEEN 0.0 AND 1.0)

);

CREATE INDEX idx_visual_doc ON visual_evidence_artifacts(doc_id, timestamp_start_sec);

CREATE INDEX idx_visual_moat ON visual_evidence_artifacts(moat_implication);



-- 11. LLM Knowledge Distillation Log (Pillar 4)

CREATE TABLE distillation_runs (

 run_id SERIAL PRIMARY KEY,

 run_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

 source_type VARCHAR(50),

 chunks_distilled INT NOT NULL,

 vectors_purged INT NOT NULL,

 summary JSONB,

 moat_updates JSONB

);



-- 12. Stored Procedure: Automated Embedding & Ghost Node Pruner (Pillar 3B)

CREATE OR REPLACE PROCEDURE prune_decayed_signals()

LANGUAGE plpgsql

AS $$

BEGIN

    -- Drop vector embeddings older than 12 months (retain raw text for relational lookup) unless Structural Milestone flagged

    UPDATE document_chunks dc

    SET embedding = NULL

    FROM raw_documents rd

    WHERE dc.doc_id = rd.doc_id

      AND rd.published_date < CURRENT_DATE - INTERVAL '12 months'

      AND dc.embedding IS NOT NULL

      AND COALESCE(rd.source_type,'') NOT ILIKE '%Structural Milestone%';



    -- Prune obsolete downstream ripple effects: probability <0.10 OR raw*prob <0.50

    DELETE FROM ripple_effects

    WHERE parent_ripple_id IS NOT NULL

      AND (

          probability < 0.10

          OR (ABS(raw_magnitude) * probability) < 0.50

      );



    -- Mark macro events older than 24 months as Archived

    UPDATE macro_events

    SET event_category = 'Archived'

    WHERE announcement_date < CURRENT_DATE - INTERVAL '24 months'

      AND event_category != 'Archived';



    -- Expire hot-tier video/audio temp buffers (document_chunks for MP4 with no cold archive flag)

    -- Cold archive to S3 Glacier assumed external; local temp already deleted via ingestion pipeline post-transcription



    COMMIT;

END;

$$;



-- 13. Time-Decayed Significance View (query-time decay without mutation)

CREATE OR REPLACE VIEW v_ripple_decayed AS

WITH decay AS (SELECT category, lambda FROM pruning_decay_config)

SELECT

  r.ripple_id,

  r.event_id,

  r.order_level,

  COALESCE(c.ticker, ind.industry_name, 'Macro') AS target,

  r.transmission_channel,

  r.raw_magnitude,

  r.probability,

  r.lag_time_months,

  -- Compound probability chain via parent join not materialized here; use recursive CTE for full path

  (r.significance_rank * EXP(-d.lambda * GREATEST(0, EXTRACT(MONTH FROM AGE(CURRENT_DATE, me.announcement_date))::NUMERIC))) AS decayed_significance,

  d.lambda

FROM ripple_effects r

JOIN macro_events me ON r.event_id=me.event_id

JOIN raw_documents rd ON me.doc_id=rd.doc_id

LEFT JOIN pruning_decay_config d ON (

  CASE WHEN rd.source_type ILIKE '%YouTube%' OR rd.source_type ILIKE '%Analyst%' THEN 'Analyst Commentary / YouTube'

       WHEN rd.source_type ILIKE '%Concall%' OR rd.source_type ILIKE '%MPC%' THEN 'Quarterly Concall / MPC Stance'

       ELSE 'Union Budget / Tax Reform' END

) = d.category

LEFT JOIN companies c ON r.target_company_id=c.company_id

LEFT JOIN industries ind ON r.target_industry_id=ind.industry_id;



-- 14. Cold-tier export helper (example: monthly cron dumps >36m chunks to parquet)

-- COPY (SELECT * FROM document_chunks WHERE published_date < CURRENT_DATE - INTERVAL '36 months') TO '/s3/parquet/...' (FORMAT PARQUET);


-- Patch to postgres_schema.sql for 4-pillar pruning + visual alpha
-- Append after existing DDL

-- 7. Data Lifecycle & Retention (Pillar 1: Tiering)
-- Hot tier: last 12 months embeddings retained, Warm: 12-36m text only, Cold: >36m parquet export
-- Enforced via prune_decayed_signals() below

-- 8. Partition document_chunks by published_date (Pillar 3A) — alternative declarative partition
-- Note: replaces non-partitioned document_chunks if fresh install. For migration, recreate:
-- DROP TABLE document_chunks; then use partitioned DDL below. SQLite fallback keeps non-partitioned.

-- Partitioned variant (use for new PG clusters)
-- CREATE TABLE document_chunks (
--     chunk_id BIGSERIAL,
--     doc_id INT NOT NULL REFERENCES raw_documents(doc_id) ON DELETE CASCADE,
--     chunk_index INT NOT NULL,
--     content TEXT NOT NULL,
--     embedding VECTOR(1536),
--     published_date DATE NOT NULL,
--     timestamp_start_sec INT,
--     timestamp_end_sec INT,
--     sector_id INT,
--     industry_id INT REFERENCES industries(industry_id),
--     PRIMARY KEY (chunk_id, published_date)
-- ) PARTITION BY RANGE (published_date);
-- CREATE TABLE document_chunks_2026_q1 PARTITION OF document_chunks FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
-- CREATE TABLE document_chunks_2026_q2 PARTITION OF document_chunks FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');
-- CREATE TABLE document_chunks_2026_q3 PARTITION OF document_chunks FOR VALUES FROM ('2026-07-01') TO ('2026-10-01');
-- CREATE TABLE document_chunks_2026_q4 PARTITION OF document_chunks FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');
-- CREATE INDEX ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);
-- Automated partition creation via pg_partman or cron.

-- 9. Decay & Graph Pruning Constants (Pillar 2)
CREATE TABLE pruning_decay_config (
 category VARCHAR(50) PRIMARY KEY, -- Analyst Commentary / YouTube, Concall/MPC, Budget/Tax Reform
 half_life_months NUMERIC(4,2) NOT NULL,
 lambda NUMERIC(6,4) GENERATED ALWAYS AS (LN(2) / half_life_months) STORED,
 significance_floor NUMERIC(4,2) DEFAULT 5.0,
 prob_cutoff NUMERIC(3,2) DEFAULT 0.08
);
INSERT INTO pruning_decay_config (category, half_life_months) VALUES
 ('Analyst Commentary / YouTube', 3),
 ('Quarterly Concall / MPC Stance', 6),
 ('Union Budget / Tax Reform', 12),
 ('State Budget', 12),
 ('PIB Circular', 3),
 ('RBI Report / Economic Survey', 6),
 ('Economic Survey', 12)
ON CONFLICT DO NOTHING;

-- 10. Visual Evidence Artifacts (Pillar: Multimodal Vision)
CREATE TABLE visual_evidence_artifacts (
 artifact_id SERIAL PRIMARY KEY,
 doc_id INT REFERENCES raw_documents(doc_id) ON DELETE CASCADE,
 chunk_id INT REFERENCES document_chunks(chunk_id) ON DELETE SET NULL,
 timestamp_start_sec INT NOT NULL,
 timestamp_end_sec INT,
 artifact_type VARCHAR(50) CHECK (artifact_type IN ('Financial_Table_Slide','Value_Chain_Diagram','Factory_Floor_Tour','Product_Tear_Down','CapEx_Timeline_Roadmap')),
 extracted_visual_data JSONB,
 visual_description TEXT NOT NULL,
 moat_implication TEXT,
 frame_snapshot_url TEXT,
 confidence_score NUMERIC(3,2) CHECK (confidence_score BETWEEN 0.0 AND 1.0)
);
CREATE INDEX idx_visual_doc ON visual_evidence_artifacts(doc_id, timestamp_start_sec);
CREATE INDEX idx_visual_moat ON visual_evidence_artifacts(moat_implication);

-- 11. LLM Knowledge Distillation Log (Pillar 4)
CREATE TABLE distillation_runs (
 run_id SERIAL PRIMARY KEY,
 run_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 source_type VARCHAR(50),
 chunks_distilled INT NOT NULL,
 vectors_purged INT NOT NULL,
 summary JSONB,
 moat_updates JSONB
);

-- 12. Stored Procedure: Automated Embedding & Ghost Node Pruner (Pillar 3B)
CREATE OR REPLACE PROCEDURE prune_decayed_signals()
LANGUAGE plpgsql
AS $$
BEGIN
    -- Drop vector embeddings older than 12 months (retain raw text for relational lookup) unless Structural Milestone flagged
    UPDATE document_chunks dc
    SET embedding = NULL
    FROM raw_documents rd
    WHERE dc.doc_id = rd.doc_id
      AND rd.published_date < CURRENT_DATE - INTERVAL '12 months'
      AND dc.embedding IS NOT NULL
      AND COALESCE(rd.source_type,'') NOT ILIKE '%Structural Milestone%';

    -- Prune obsolete downstream ripple effects: probability <0.10 OR raw*prob <0.50
    DELETE FROM ripple_effects
    WHERE parent_ripple_id IS NOT NULL
      AND (
          probability < 0.10
          OR (ABS(raw_magnitude) * probability) < 0.50
      );

    -- Mark macro events older than 24 months as Archived
    UPDATE macro_events
    SET event_category = 'Archived'
    WHERE announcement_date < CURRENT_DATE - INTERVAL '24 months'
      AND event_category != 'Archived';

    -- Expire hot-tier video/audio temp buffers (document_chunks for MP4 with no cold archive flag)
    -- Cold archive to S3 Glacier assumed external; local temp already deleted via ingestion pipeline post-transcription

    COMMIT;
END;
$$;

-- 13. Time-Decayed Significance View (query-time decay without mutation)
CREATE OR REPLACE VIEW v_ripple_decayed AS
WITH decay AS (SELECT category, lambda FROM pruning_decay_config)
SELECT
  r.ripple_id,
  r.event_id,
  r.order_level,
  COALESCE(c.ticker, ind.industry_name, 'Macro') AS target,
  r.transmission_channel,
  r.raw_magnitude,
  r.probability,
  r.lag_time_months,
  -- Compound probability chain via parent join not materialized here; use recursive CTE for full path
  (r.significance_rank * EXP(-d.lambda * GREATEST(0, EXTRACT(MONTH FROM AGE(CURRENT_DATE, me.announcement_date))::NUMERIC))) AS decayed_significance,
  d.lambda
FROM ripple_effects r
JOIN macro_events me ON r.event_id=me.event_id
JOIN raw_documents rd ON me.doc_id=rd.doc_id
LEFT JOIN pruning_decay_config d ON (
  CASE WHEN rd.source_type ILIKE '%YouTube%' OR rd.source_type ILIKE '%Analyst%' THEN 'Analyst Commentary / YouTube'
       WHEN rd.source_type ILIKE '%Concall%' OR rd.source_type ILIKE '%MPC%' THEN 'Quarterly Concall / MPC Stance'
       ELSE 'Union Budget / Tax Reform' END
) = d.category
LEFT JOIN companies c ON r.target_company_id=c.company_id
LEFT JOIN industries ind ON r.target_industry_id=ind.industry_id;


-- 15. Corporate Documents / Actions / Status Mirrors (SQLite parity)
-- Mirrors reality_engine/db/schema.sql sections 12, 12b, 12c for PostgreSQL so the
-- production PG store and the local SQLite WAL fallback share an identical entity model.

CREATE TABLE IF NOT EXISTS corporate_documents (
    doc_id SERIAL PRIMARY KEY,
    isin TEXT NOT NULL,
    symbol TEXT NOT NULL,
    doc_type TEXT NOT NULL,              -- 'CONCALL_TRANSCRIPT', 'INVESTOR_PRESENTATION', 'ANNUAL_REPORT', 'ANNOUNCEMENT'
    title TEXT NOT NULL,
    doc_date DATE NOT NULL,
    source_url TEXT,
    source TEXT,                         -- provenance: 'bse_official' | 'nse_official' | 'screener_discovery'
    discovery_source TEXT,               -- where the link was discovered: 'screener_discovery' etc.
    local_file_path TEXT,
    file_size_bytes BIGINT,
    sha256_hash TEXT,
    is_processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_url)                  -- idempotent upsert key (mirrors SQLite UNIQUE(source_url))
);

CREATE INDEX IF NOT EXISTS idx_corp_docs_symbol ON corporate_documents(symbol);
CREATE INDEX IF NOT EXISTS idx_corp_docs_isin ON corporate_documents(isin);
CREATE INDEX IF NOT EXISTS idx_corp_docs_doc_date ON corporate_documents(doc_date DESC);
CREATE INDEX IF NOT EXISTS idx_corp_docs_source_url ON corporate_documents(source_url);


CREATE TABLE IF NOT EXISTS corporate_actions (
    action_id SERIAL PRIMARY KEY,
    isin TEXT NOT NULL,
    symbol TEXT NOT NULL,
    company_name TEXT,
    subject TEXT,                        -- raw NSE subject line
    action_type TEXT NOT NULL,           -- normalized: DIVIDEND, BONUS, SPLIT, RIGHTS, BUYBACK, MERGER, DEMERGER, INTEREST, AGM, OTHER
    ex_date DATE,
    rec_date DATE,
    bc_start_date DATE,                  -- book-closure start
    bc_end_date DATE,                    -- book-closure end
    nd_start_date DATE,                  -- no-delivery start
    nd_end_date DATE,                    -- no-delivery end
    broadcast_date DATE,
    face_value NUMERIC(10,2),
    series TEXT,
    industry TEXT,
    source TEXT DEFAULT 'nse_official',
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (isin, subject, ex_date, action_type)
);

CREATE INDEX IF NOT EXISTS idx_ca_isin ON corporate_actions(isin);
CREATE INDEX IF NOT EXISTS idx_ca_symbol ON corporate_actions(symbol);
CREATE INDEX IF NOT EXISTS idx_ca_type ON corporate_actions(action_type);


CREATE TABLE IF NOT EXISTS corporate_status_flags (
    flag_id SERIAL PRIMARY KEY,
    isin TEXT,
    symbol TEXT NOT NULL,
    status_type TEXT NOT NULL,           -- DELISTED | SUSPENDED | NCLT_CIRP | INSOLVENCY_RISK
    source TEXT NOT NULL,                -- nse_official | bse_official | announcement_scan | derived
    detail TEXT,                         -- free-text reason / proceeding reference
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (symbol, status_type, source)
);

CREATE INDEX IF NOT EXISTS idx_csf_symbol ON corporate_status_flags(symbol);
CREATE INDEX IF NOT EXISTS idx_csf_type ON corporate_status_flags(status_type);


-- 14. Cold-tier export helper (example: monthly cron dumps >36m chunks to parquet)
-- COPY (SELECT * FROM document_chunks WHERE published_date < CURRENT_DATE - INTERVAL '36 months') TO '/s3/parquet/...' (FORMAT PARQUET);


-- 16. Wave C — Structural-milestone survival migration (additive; half-life INF).
-- STRUCTURAL_THEORY milestones (profit-jump spotting, cheap-value traps) carry
-- is_structural_milestone=1 and must NEVER be decayed nor pruned. Additive ALTERs
-- (safe on a populated PG cluster; no-op if the columns already exist).
ALTER TABLE pruning_decay_config ADD COLUMN IF NOT EXISTS is_structural_milestone INTEGER DEFAULT 0;
ALTER TABLE raw_documents ADD COLUMN IF NOT EXISTS is_structural_milestone INTEGER DEFAULT 0;
-- A dedicated structural-milestone decay category (T½ INF -> lambda 0) so the
-- v_ripple_decayed view keeps S(t) == S0 for permanent priors.
INSERT INTO pruning_decay_config (category, half_life_months, is_structural_milestone)
VALUES ('Structural Milestone', 9999, 1)
ON CONFLICT (category) DO UPDATE SET is_structural_milestone = 1;

