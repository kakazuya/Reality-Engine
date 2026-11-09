-- Store v2 schema contract (T-131, Wolf, 9 Nov 2026). DRAFT until Shivam's OK.
-- One file per company (<catalog root>/company/<ISIN>.db) holds every table below except `catalog_company`
-- (catalog.db) and the market series (DuckDB over Parquet, see docs/V2_SCHEMA_CONTRACT.md section 6).
-- Rules every table keeps:
--   * known_at on every row that a past date may see (ISO, IST, from the filing record; never the crawl date).
--   * values in base units (rupees, units, tonnes, percent as 12.5 not 0.125); the printed unit text and scale
--     ride alongside so a reader can show what the page said (T-150). The read side never converts.
--   * no model-inferred value is stored as a fact (Shivam 7 Nov). Model output may only pick a label mapping
--     that Opus approves (label_map.status) or record a verbatim quote.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- 1. who: entities (T-149)
-- The listed company is entity 1 of its file. Segments, subsidiaries, brands, geographies and joint ventures
-- are entities linked to it, so "Blinkit GOV", "Novelis rating", "BHFL share of PAT" are ordinary lookups.
CREATE TABLE IF NOT EXISTS entity (
    entity_id     INTEGER PRIMARY KEY,
    isin          TEXT NOT NULL,              -- the listed parent's current ISIN
    name          TEXT NOT NULL,              -- 'Blinkit', 'Novelis Inc.', 'Bajaj Housing Finance', 'India'
    kind          TEXT NOT NULL CHECK (kind IN ('company','segment','subsidiary','associate','jv','brand',
                                                 'geography','business_line','plant')),
    parent_id     INTEGER REFERENCES entity(entity_id),
    listed_isin   TEXT,                       -- when the entity itself is listed (HDB Financial, Indus Towers)
    stake_pct     REAL,                       -- latest stated holding; history lives in fact rows
    valid_from    TEXT, valid_to TEXT,        -- acquisition / demerger dates
    source_ref    TEXT                        -- evidence id that named it
);
CREATE TABLE IF NOT EXISTS entity_alias (
    alias         TEXT NOT NULL,              -- normalised: lower case, no punctuation
    entity_id     INTEGER NOT NULL REFERENCES entity(entity_id),
    PRIMARY KEY (alias, entity_id)
);

-- ---------------------------------------------------------------- 2. when: periods (T-134)
-- Every value points at one period row with exact dates; the label is derived, never parsed at read time.
CREATE TABLE IF NOT EXISTS period (
    period_id     TEXT PRIMARY KEY,           -- '2026-07-01/2026-09-30'
    start_date    TEXT,                       -- NULL for a point in time (balance sheet, stock date)
    end_date      TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('Q','H1','H2','9M','FY','TTM','M','YTD','POINT','OTHER')),
    fiscal_label  TEXT NOT NULL               -- 'Q2FY27', 'H1FY27', 'FY26', 'TTM to Q2FY27', '30 Sep 2026'
);

-- ---------------------------------------------------------------- 3. evidence (cold): documents, pages, tables
CREATE TABLE IF NOT EXISTS doc (
    doc_key       TEXT PRIMARY KEY,
    sha256        TEXT NOT NULL,              -- build is keyed by content hash (T-148)
    doc_type      TEXT NOT NULL,              -- our own type dictionary, never the exchange category
    title         TEXT, filing_date TEXT, known_at TEXT, pages INTEGER,
    event_id      INTEGER,                    -- the event this document belongs to (a call and its transcript share one)
    parse_version TEXT,                       -- parser that produced doc_page/table_cell (T-147)
    source        TEXT, source_key TEXT
);
CREATE TABLE IF NOT EXISTS doc_page (
    doc_key TEXT NOT NULL REFERENCES doc(doc_key), page INTEGER NOT NULL,
    text TEXT, method TEXT, ocr_conf REAL, section TEXT,  -- section: 'standalone results', 'note 38 contingent liabilities'
    PRIMARY KEY (doc_key, page)
);
-- T-132: every printed table cell. One row per cell, header text kept verbatim so a later label map re-reads it.
CREATE TABLE IF NOT EXISTS table_cell (
    cell_id       INTEGER PRIMARY KEY,
    doc_key       TEXT NOT NULL REFERENCES doc(doc_key),
    page          INTEGER NOT NULL,
    table_no      INTEGER NOT NULL,           -- n-th table on the page
    row_no        INTEGER NOT NULL, col_no INTEGER NOT NULL,
    row_label     TEXT,                       -- verbatim, with parent labels joined by ' > ' for indented rows
    col_header    TEXT,                       -- verbatim, multi-line headers joined by ' > '
    period_id     TEXT REFERENCES period(period_id),   -- resolved from the column header + document date
    basis         TEXT CHECK (basis IN ('standalone','consolidated') OR basis IS NULL),
    value_text    TEXT NOT NULL,              -- token as printed: '(1,234.5)', '12.3%', '-'
    value         REAL,                       -- base units after scale and sign
    unit_text     TEXT, scale REAL,           -- 'Rs crore', 1e7
    bbox          TEXT,                       -- x0,y0,x1,y1 for the page viewer
    method        TEXT NOT NULL               -- 'text_layer' | 'ocr' | 'model' (model only where scripts fail, labelled)
);
CREATE INDEX IF NOT EXISTS ix_cell_label ON table_cell(row_label);
CREATE INDEX IF NOT EXISTS ix_cell_doc ON table_cell(doc_key, page, table_no);
-- verbatim statements (calls, press releases, letters): what management said, with speaker and context
CREATE TABLE IF NOT EXISTS statement (
    statement_id  INTEGER PRIMARY KEY,
    doc_key       TEXT NOT NULL REFERENCES doc(doc_key), page INTEGER,
    event_id      INTEGER,
    speaker       TEXT, role TEXT,            -- 'CFO', 'analyst'
    question_text TEXT,                       -- the analyst question it answers, verbatim
    quote         TEXT NOT NULL,
    topics        TEXT,                       -- metric ids it mentions (label_map vocabulary), comma separated
    entity_id     INTEGER REFERENCES entity(entity_id),
    known_at      TEXT NOT NULL
);

-- ---------------------------------------------------------------- 4. facts (hot)
-- T-133: one approved mapping from a printed label to a metric, per sector family. Opus approves a family once.
CREATE TABLE IF NOT EXISTS label_map (
    label_norm    TEXT NOT NULL,              -- normalised row label
    sector_family TEXT NOT NULL,              -- 'telecom', 'paints', '*' for all
    metric        TEXT NOT NULL,              -- 'arpu_mobile', 'utilisation_excl_trainees'
    dimension     TEXT,                       -- 'geography=India', 'measure=cc_growth'
    unit_kind     TEXT,                       -- 'inr','pct','count','tonnes','days','x'
    status        TEXT NOT NULL CHECK (status IN ('approved','queue','rejected')),
    approved_by   TEXT, approved_at TEXT,
    PRIMARY KEY (label_norm, sector_family, dimension)
);
-- T-133: what a metric IS, so the period engine sums only flows. One row per metric id used by label_map/fact.
CREATE TABLE IF NOT EXISTS metric_def (
    metric        TEXT PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('flow','stock','ratio','per_share','count','price')),
    unit_kind     TEXT,                       -- 'inr','usd','pct','count','tonnes','days','x','inr_per_share'
    description   TEXT
);
-- One row per entity x metric x dimension x period x basis x definition. Several documents printing the same
-- figure are ONE fact with several evidence rows (T-146). Restatements are new rows with a later known_at.
CREATE TABLE IF NOT EXISTS fact (
    fact_id       INTEGER PRIMARY KEY,
    entity_id     INTEGER NOT NULL REFERENCES entity(entity_id),
    metric        TEXT NOT NULL,
    dimension     TEXT NOT NULL DEFAULT '',
    period_id     TEXT NOT NULL REFERENCES period(period_id),
    basis         TEXT NOT NULL CHECK (basis IN ('standalone','consolidated','segment','na')),
    definition    TEXT NOT NULL DEFAULT 'reported',  -- 'reported','adjusted','company_stated','incl_trainees'...
    kind          TEXT NOT NULL CHECK (kind IN ('reported','stated','derived')),
    value         REAL NOT NULL,              -- base units
    unit          TEXT NOT NULL,              -- 'inr','pct','count','tonnes','days','x','inr_per_share'
    known_at      TEXT NOT NULL,
    superseded_at TEXT,                       -- known_at of the restatement that replaced it; NULL = current
    check_status  TEXT NOT NULL DEFAULT 'unverified'
                  CHECK (check_status IN ('verified','unverified','quarantined')),
    check_detail  TEXT
);
CREATE INDEX IF NOT EXISTS ix_fact_key ON fact(entity_id, metric, period_id, known_at);
CREATE TABLE IF NOT EXISTS fact_evidence (
    fact_id       INTEGER NOT NULL REFERENCES fact(fact_id),
    evidence_kind TEXT NOT NULL CHECK (evidence_kind IN ('table_cell','xbrl','statement','page','store_row')),
    evidence_ref  TEXT NOT NULL,              -- cell_id, xbrl file#rowid, statement_id, doc_key#page
    agrees        INTEGER NOT NULL DEFAULT 1, -- 0 when this source printed a different number (kept, flagged)
    PRIMARY KEY (fact_id, evidence_kind, evidence_ref)
);
-- T-134/T-135 stored derivations: quarters from 9M/FY, TTM, YoY, shares. Inputs are fact ids, never numbers.
CREATE TABLE IF NOT EXISTS derivation (
    fact_id       INTEGER PRIMARY KEY REFERENCES fact(fact_id),   -- the derived fact (kind='derived')
    formula_id    TEXT NOT NULL,              -- calc catalog id: 'Q_FROM_FY_LESS_9M', 'TTM_SUM4', 'YOY'
    input_ids     TEXT NOT NULL               -- JSON list of fact ids in formula order
);

-- ---------------------------------------------------------------- 5. forward statements, events, notes, gaps
-- T-137: every forward target verbatim, linked to the target it revises and to the outcome fact once reported.
CREATE TABLE IF NOT EXISTS guidance (
    guidance_id   INTEGER PRIMARY KEY,
    entity_id     INTEGER NOT NULL REFERENCES entity(entity_id),
    metric        TEXT NOT NULL, dimension TEXT NOT NULL DEFAULT '',
    target_period_id TEXT REFERENCES period(period_id),
    low REAL, high REAL, unit TEXT, direction TEXT,     -- direction: 'up','down','flat','range','at_least','at_most'
    event_id      INTEGER,                    -- the call / meeting where it was said (one event per call)
    statement_id  INTEGER REFERENCES statement(statement_id),
    revises_id    INTEGER REFERENCES guidance(guidance_id),
    outcome_fact_id INTEGER REFERENCES fact(fact_id),
    known_at      TEXT NOT NULL
);
-- T-140: dated events. A results day, a call, an order win, a tariff, a rating action, an acquisition.
CREATE TABLE IF NOT EXISTS event (
    event_id      INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,              -- 'results','call','order','policy','tariff','regulation','rating',
                                              -- 'm_and_a','capital_raise','dividend','management','other'
    title         TEXT NOT NULL,
    announced_at  TEXT NOT NULL,              -- IST timestamp; day 0 = next session when after 15:30
    effective_date TEXT,
    session_day0  TEXT,                       -- precomputed trading day 0 (filing timing rule)
    size_value REAL, size_unit TEXT,          -- order value, deal value, tariff rate
    source_ref    TEXT NOT NULL,              -- doc_key / outside-source id
    scope         TEXT NOT NULL DEFAULT 'company'  -- 'company' | 'sector' | 'economy'
);
CREATE TABLE IF NOT EXISTS event_entity (
    event_id INTEGER NOT NULL REFERENCES event(event_id),
    entity_id INTEGER NOT NULL REFERENCES entity(entity_id),
    role TEXT,                                -- 'issuer','counterparty','affected'
    PRIMARY KEY (event_id, entity_id)
);
-- T-138: annual-report notes as typed rows (guarantees, contingent liabilities, related parties, FX sensitivity,
-- ratings, borrowings by currency). Standalone and consolidated pages stay apart.
CREATE TABLE IF NOT EXISTS note_item (
    note_id       INTEGER PRIMARY KEY,
    entity_id     INTEGER NOT NULL REFERENCES entity(entity_id),
    note_type     TEXT NOT NULL CHECK (note_type IN ('guarantee','contingent_liability','related_party',
                     'fx_sensitivity','fx_exposure','rating','borrowing','commitment','segment','concentration',
                     'share_based_payment','other')),
    basis         TEXT NOT NULL CHECK (basis IN ('standalone','consolidated')),
    counterparty  TEXT,                       -- related party, guaranteed subsidiary, agency
    item          TEXT,                       -- 'performance guarantee', 'USD', 'CRISIL AAA/Stable'
    amount REAL, unit TEXT, currency TEXT,
    period_id     TEXT REFERENCES period(period_id),
    doc_key TEXT NOT NULL, page INTEGER NOT NULL, quote TEXT NOT NULL,
    known_at      TEXT NOT NULL
);
-- T-141: what the company does NOT disclose, as a stored fact, with what was searched.
CREATE TABLE IF NOT EXISTS disclosure (
    entity_id     INTEGER NOT NULL REFERENCES entity(entity_id),
    metric        TEXT NOT NULL, dimension TEXT NOT NULL DEFAULT '',
    period_kind   TEXT NOT NULL,              -- 'Q','FY' ... (a metric disclosed yearly only is a finding)
    status        TEXT NOT NULL CHECK (status IN ('disclosed','not_disclosed','not_held','stopped')),
    first_period  TEXT, last_period TEXT,     -- range of periods it was disclosed in
    searched      TEXT,                       -- JSON: doc types and periods read before writing not_disclosed
    checked_at    TEXT NOT NULL,
    PRIMARY KEY (entity_id, metric, dimension, period_kind)
);

-- ---------------------------------------------------------------- 6. outside sources (T-139), questions (T-151)
CREATE TABLE IF NOT EXISTS outside_doc (
    outside_id    INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,              -- 'crisil','icra','care','indra','siam','dpiit','pib','budget','rbi','sebi'
    kind          TEXT NOT NULL,              -- 'rating_rationale','industry_monthly','budget_line','circular'
    title TEXT, published_at TEXT NOT NULL, url TEXT, sha256 TEXT, text TEXT
);
CREATE TABLE IF NOT EXISTS question_template (
    template_id   TEXT PRIMARY KEY,           -- 'NPA_LATEST', 'APE_VNB_4Q', 'EV_EBITDA_TODAY'
    text          TEXT NOT NULL,              -- 'What were {company}'s gross NPA, net NPA ... in {period}?'
    needs         TEXT NOT NULL,              -- JSON list of fact keys / calc ids / event kinds it needs
    family        TEXT                        -- sector family or '*'
);
