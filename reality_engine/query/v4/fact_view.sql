-- =============================================================================
-- fact_view.sql - the v4 long-format fact view (QUERY_V4_DESIGN §B.1, §H.2).
-- Materialised as a table, which is the one place §B.1 says a table is right
-- ("the fact view itself at scale, because the panel assembly is the real cost,
-- not the algebra").  Rebuild with build_membership.py; it is a snapshot of the
-- pilot stores, deterministic from them.
--
-- Apply to a build DB that has these ATTACH aliases (build_membership.py attaches
-- them read-only, immutable=1) and the seed table pilot_universe(isin, symbol):
--   market_state    pilot/pilot60/market_state_pilot.db  (T1 market state)
--   facts_pilot     pilot/pilot60/facts_pilot.db         (T1 facts: XBRL metric series)
--   market_state_b  pilot/pilot60/market_state_b.db      (pilot (b): bhavcopy, F&O, macro)
--   metric_state    pilot/pilot60/extract_pilot60.db     (targeted extraction, extract60.py)
--   chunks_v3       pilot/pilot60/chunks_v3_pilot.db     (passages)
--
-- Shape: entity_id, atom, dims, period_start, period_end, value, unit, known_at,
-- source_ref.  Key: (entity_id, atom, dims, period_start, period_end) - one row per
-- entity/atom/period *per dim combination*, which is the design's key (NSE vs BSE,
-- consolidated vs standalone, one F&O contract, ...).  text.passage is the one atom
-- that keeps chunk_id in dims, because one document has one row per passage.
--
-- PIT: `known_at` is copied from the source where it has one; for session-dated
-- market tables it is `date || 'T23:59:59'` (date-only source -> end of day IST, the
-- house convention in truth_*.duckdb).  Never earlier than the source's own record.
--
-- Units are the source's own (INR, INR_CRORE, INR_PER_SHARE, INR_LAKH, shares, %, ...);
-- nothing is rescaled, so a hand check compares against the source column directly.
--
-- atom -> pilot source (the full-scale source is the registry's `source` field):
--   price.close / mcap / shares_out  market_state.company_state_daily
--                                    (close = raw_close, the TRADED close; see below)
--   price.open .. traded_value       market_state_b.mkt_nse_full_daily (NSE, symbol->ISIN)
--   price.band                       market_state.price_band_daily
--   fin.revenue .. interest_expense  facts_pilot.company_metric_series (by metric_key)
--   fin.ebitda                       derived: pbt + finance_costs + depreciation
--   fin.total_debt                   derived: borrowings_current + borrowings_noncurrent
--   fin.segment_value                facts_pilot.company_segment_pnl
--   fin.capacity_utilisation        metric_state.company_capacity_utilisation
--   fin.order_book / order_intake    metric_state.order_intake
--   hold.pct / hold.pledge_pct       market_state.company_ownership_pit
--   flows.net_inr                    market_state.event_leakage_window (empty here)
--   text.passage                     chunks_v3.chunk
--   macro.commodity_close            market_state_b.series_observation (kind='commodity')
--   macro.series                     market_state_b.series_observation
-- The atoms whose source is outside the five pilot files (results_xbrl.db,
-- equity_intelligence.db, pilot/macro_all.db) are added by fact_view_extras.sql;
-- `macro.oi` is written to the attached side file by fact_oi.sql, not here.
-- =============================================================================

DROP TABLE IF EXISTS fact;
CREATE TABLE fact(
    entity_id    TEXT NOT NULL,
    atom         TEXT NOT NULL,
    dims         TEXT NOT NULL DEFAULT '',
    period_start TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    value,                       -- REAL for measures, TEXT for text.passage/claim
    unit         TEXT,
    known_at     TEXT NOT NULL,
    source_ref   TEXT NOT NULL,
    -- one row per entity/atom/period per dim combination; WITHOUT ROWID keeps the
    -- key order (entity, atom) as the storage order, so a point lookup is one seek.
    PRIMARY KEY (entity_id, atom, dims, period_start, period_end)
) WITHOUT ROWID;

-- ---------------------------------------------------------------------------
-- market: price.close / mcap / shares_out  (T1 panel: NSE close, BSE fallback)
-- price.close is the TRADED close: company_state_daily.raw_close (build_t1.py).
-- company_state_daily.close is px_daily.adj_close, adjusted for capital actions that
-- may come AFTER the date; loading it here would put later knowledge into a level as
-- of the date and mix bases with price.open/high/low.  A return is computed over the
-- adjusted series at query time (execute.price_basis), never by storing it as the
-- close.  The basis is declared in dims so a reader can name it.
-- ---------------------------------------------------------------------------
INSERT INTO fact
SELECT s.isin, 'price.close', 'basis=raw', s.date, s.date, s.raw_close, 'INR', s.known_at,
       'market_state.company_state_daily'
FROM market_state.company_state_daily s
JOIN pilot_universe u ON u.isin = s.isin
WHERE s.raw_close IS NOT NULL;

INSERT INTO fact
SELECT s.isin, 'price.mcap', '', s.date, s.date, s.mcap_cr, 'INR_CRORE', s.known_at,
       'market_state.company_state_daily'
FROM market_state.company_state_daily s
JOIN pilot_universe u ON u.isin = s.isin
WHERE s.mcap_cr IS NOT NULL;

INSERT INTO fact
SELECT s.isin, 'price.shares_out', '', s.date, s.date, s.shares_out, 'shares', s.known_at,
       'market_state.company_state_daily'
FROM market_state.company_state_daily s
JOIN pilot_universe u ON u.isin = s.isin
WHERE s.shares_out IS NOT NULL;

-- ---------------------------------------------------------------------------
-- market: price.open/high/low/volume/delivery_qty/delivery_pct/traded_value
-- The NSE bhavcopy is symbol-keyed; pilot_universe carries the pilot symbol.
-- series is included once per (symbol, date) in the held bhavcopy (verified), so no
-- series preference is applied - the unique key would reject a duplicate.
-- ---------------------------------------------------------------------------
INSERT INTO fact
SELECT u.isin, 'price.open', 'exchange=NSE', b.date, b.date, b.open, 'INR',
       b.date || 'T23:59:59', 'market_state_b.mkt_nse_full_daily'
FROM market_state_b.mkt_nse_full_daily b
JOIN pilot_universe u ON u.symbol = b.symbol
WHERE b.open IS NOT NULL AND b.symbol <> '';

INSERT INTO fact
SELECT u.isin, 'price.high', 'exchange=NSE', b.date, b.date, b.high, 'INR',
       b.date || 'T23:59:59', 'market_state_b.mkt_nse_full_daily'
FROM market_state_b.mkt_nse_full_daily b
JOIN pilot_universe u ON u.symbol = b.symbol
WHERE b.high IS NOT NULL AND b.symbol <> '';

INSERT INTO fact
SELECT u.isin, 'price.low', 'exchange=NSE', b.date, b.date, b.low, 'INR',
       b.date || 'T23:59:59', 'market_state_b.mkt_nse_full_daily'
FROM market_state_b.mkt_nse_full_daily b
JOIN pilot_universe u ON u.symbol = b.symbol
WHERE b.low IS NOT NULL AND b.symbol <> '';

INSERT INTO fact
SELECT u.isin, 'price.volume', 'exchange=NSE', b.date, b.date, b.volume, 'shares',
       b.date || 'T23:59:59', 'market_state_b.mkt_nse_full_daily'
FROM market_state_b.mkt_nse_full_daily b
JOIN pilot_universe u ON u.symbol = b.symbol
WHERE b.volume IS NOT NULL AND b.symbol <> '';

INSERT INTO fact
SELECT u.isin, 'price.delivery_qty', 'exchange=NSE', b.date, b.date, b.deliverable_qty,
       'shares', b.date || 'T23:59:59', 'market_state_b.mkt_nse_full_daily'
FROM market_state_b.mkt_nse_full_daily b
JOIN pilot_universe u ON u.symbol = b.symbol
WHERE b.deliverable_qty IS NOT NULL AND b.symbol <> '';

INSERT INTO fact
SELECT u.isin, 'price.delivery_pct', 'exchange=NSE', b.date, b.date, b.delivery_pct, '%',
       b.date || 'T23:59:59', 'market_state_b.mkt_nse_full_daily'
FROM market_state_b.mkt_nse_full_daily b
JOIN pilot_universe u ON u.symbol = b.symbol
WHERE b.delivery_pct IS NOT NULL AND b.symbol <> '';

INSERT INTO fact
SELECT u.isin, 'price.traded_value', 'exchange=NSE', b.date, b.date, b.turnover_lacs,
       'INR_LAKH', b.date || 'T23:59:59', 'market_state_b.mkt_nse_full_daily'
FROM market_state_b.mkt_nse_full_daily b
JOIN pilot_universe u ON u.symbol = b.symbol
WHERE b.turnover_lacs IS NOT NULL AND b.symbol <> '';

-- ---------------------------------------------------------------------------
-- market: price.band (NULL band = "no band"; only a held band is a fact)
-- ---------------------------------------------------------------------------
INSERT INTO fact
SELECT p.isin, 'price.band', '', p.date, p.date, p.band, 'band',
       p.date || 'T23:59:59', 'market_state.price_band_daily'
FROM market_state.price_band_daily p
JOIN pilot_universe u ON u.isin = p.isin
WHERE p.band IS NOT NULL;

-- ---------------------------------------------------------------------------
-- fundamentals: one metric_key per atom, plus the two declared aggregates
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS _map;
CREATE TABLE _map(atom TEXT NOT NULL, metric_key TEXT NOT NULL);
INSERT INTO _map(atom, metric_key) VALUES
    ('fin.revenue',         'revenue'),
    ('fin.pat',             'pat'),
    ('fin.eps',             'eps'),
    ('fin.book_equity',     'net_worth'),
    ('fin.cash',            'cash'),
    ('fin.receivables',     'receivables'),
    ('fin.inventory',       'inventory'),
    ('fin.payables',        'payables'),
    ('fin.interest_expense','finance_costs');

INSERT INTO fact
SELECT s.isin, m.atom,
       'basis=' || COALESCE(s.basis, '') || ';period_kind=' || COALESCE(s.period_kind, ''),
       s.period_end, s.period_end, s.value, s.unit, s.known_at,
       'facts_pilot.company_metric_series'
FROM facts_pilot.company_metric_series s
JOIN _map m ON m.metric_key = s.metric_key
JOIN pilot_universe u ON u.isin = s.isin
WHERE s.value IS NOT NULL;

-- fin.ebitda: the design's atom, and EBITDA's definition; emitted only when all three
-- reported components are held for that period (a partial sum would understate it).
INSERT INTO fact
SELECT s.isin, 'fin.ebitda',
       'basis=' || COALESCE(s.basis, '') || ';period_kind=' || COALESCE(s.period_kind, ''),
       s.period_end, s.period_end, SUM(s.value), MAX(s.unit), MAX(s.known_at),
       'derived:facts_pilot.company_metric_series:pbt+finance_costs+depreciation'
FROM facts_pilot.company_metric_series s
JOIN pilot_universe u ON u.isin = s.isin
WHERE s.metric_key IN ('pbt', 'finance_costs', 'depreciation') AND s.value IS NOT NULL
GROUP BY s.isin, s.basis, s.period_kind, s.period_end
HAVING COUNT(DISTINCT s.metric_key) = 3;

-- fin.total_debt: registry says agg=sum over the two borrowings keys; both required.
INSERT INTO fact
SELECT s.isin, 'fin.total_debt',
       'basis=' || COALESCE(s.basis, '') || ';period_kind=' || COALESCE(s.period_kind, ''),
       s.period_end, s.period_end, SUM(s.value), MAX(s.unit), MAX(s.known_at),
       'derived:facts_pilot.company_metric_series:borrowings_current+borrowings_noncurrent'
FROM facts_pilot.company_metric_series s
JOIN pilot_universe u ON u.isin = s.isin
WHERE s.metric_key IN ('borrowings_current', 'borrowings_noncurrent')
  AND s.value IS NOT NULL
GROUP BY s.isin, s.basis, s.period_kind, s.period_end
HAVING COUNT(DISTINCT s.metric_key) = 2;

-- fin.segment_value: segment is a dim; one segment per (metric, basis, period).
INSERT INTO fact
SELECT p.isin, 'fin.segment_value',
       'basis=' || COALESCE(p.basis, '') || ';metric=' || COALESCE(p.metric, '') ||
       ';segment=' || COALESCE(p.segment, ''),
       p.period_end, p.period_end, p.value_cr, 'INR_CRORE', p.known_at,
       'facts_pilot.company_segment_pnl'
FROM facts_pilot.company_segment_pnl p
JOIN pilot_universe u ON u.isin = p.isin
WHERE p.value_cr IS NOT NULL;

-- fin.capacity_utilisation: product is a dim; a duplicated product/period keeps the
-- latest-known row only (the unique key below would otherwise reject it).
INSERT INTO fact
SELECT isin, 'fin.capacity_utilisation', 'product=' || COALESCE(product, ''),
       period_end, period_end, utilisation_pct, '%', known_at,
       'metric_state.company_capacity_utilisation'
FROM (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY isin, period_end, product
                                     ORDER BY known_at DESC) AS rn
      FROM metric_state.company_capacity_utilisation c)
WHERE rn = 1 AND utilisation_pct IS NOT NULL
  AND isin IN (SELECT isin FROM pilot_universe);

-- fin.order_book and fin.order_intake are two measures of one reported row.
INSERT INTO fact
SELECT o.isin, 'fin.order_book', '', o.period_end, o.period_end, o.order_book_cr,
       'INR_CRORE', o.known_at, 'metric_state.order_intake'
FROM metric_state.order_intake o
JOIN pilot_universe u ON u.isin = o.isin
WHERE o.order_book_cr IS NOT NULL;

INSERT INTO fact
SELECT o.isin, 'fin.order_intake', '', o.period_end, o.period_end, o.intake_cr,
       'INR_CRORE', o.known_at, 'metric_state.order_intake'
FROM metric_state.order_intake o
JOIN pilot_universe u ON u.isin = o.isin
WHERE o.intake_cr IS NOT NULL;

-- ---------------------------------------------------------------------------
-- ownership: hold.pct (holder_class dim) and hold.pledge_pct
-- ---------------------------------------------------------------------------
INSERT INTO fact
SELECT q.isin, 'hold.pct', 'holder_class=promoter', q.quarter_end, q.quarter_end,
       q.promoter_pct, '%', q.known_at, 'market_state.company_ownership_pit'
FROM market_state.company_ownership_pit q
JOIN pilot_universe u ON u.isin = q.isin
WHERE q.promoter_pct IS NOT NULL
UNION ALL
SELECT q.isin, 'hold.pct', 'holder_class=fii', q.quarter_end, q.quarter_end,
       q.fii_pct, '%', q.known_at, 'market_state.company_ownership_pit'
FROM market_state.company_ownership_pit q
JOIN pilot_universe u ON u.isin = q.isin
WHERE q.fii_pct IS NOT NULL
UNION ALL
SELECT q.isin, 'hold.pct', 'holder_class=dii', q.quarter_end, q.quarter_end,
       q.dii_pct, '%', q.known_at, 'market_state.company_ownership_pit'
FROM market_state.company_ownership_pit q
JOIN pilot_universe u ON u.isin = q.isin
WHERE q.dii_pct IS NOT NULL
UNION ALL
SELECT q.isin, 'hold.pct', 'holder_class=mf', q.quarter_end, q.quarter_end,
       q.mf_pct, '%', q.known_at, 'market_state.company_ownership_pit'
FROM market_state.company_ownership_pit q
JOIN pilot_universe u ON u.isin = q.isin
WHERE q.mf_pct IS NOT NULL
UNION ALL
SELECT q.isin, 'hold.pct', 'holder_class=public', q.quarter_end, q.quarter_end,
       q.public_pct, '%', q.known_at, 'market_state.company_ownership_pit'
FROM market_state.company_ownership_pit q
JOIN pilot_universe u ON u.isin = q.isin
WHERE q.public_pct IS NOT NULL;

INSERT INTO fact
SELECT q.isin, 'hold.pledge_pct', 'holder_class=promoter', q.quarter_end, q.quarter_end,
       q.pledge_pct, '%', q.known_at, 'market_state.company_ownership_pit'
FROM market_state.company_ownership_pit q
JOIN pilot_universe u ON u.isin = q.isin
WHERE q.pledge_pct IS NOT NULL;

-- flows.net_inr: the pilot's event_leakage_window is empty; the branch stays so the
-- atom is wired the day the window is filled.
INSERT INTO fact
SELECT w.isin, 'flows.net_inr', 'flow_kind=insider', w.date, w.date, w.insider_net_inr,
       'INR', w.known_at, 'market_state.event_leakage_window'
FROM market_state.event_leakage_window w
JOIN pilot_universe u ON u.isin = w.isin
WHERE w.insider_net_inr IS NOT NULL;

-- ---------------------------------------------------------------------------
-- narrative: text.passage (value is the chunk body; chunk_id keeps the key unique)
-- ---------------------------------------------------------------------------
INSERT INTO fact
SELECT c.isin, 'text.passage',
       'doctype=' || COALESCE(c.doc_type, '') ||
       CASE WHEN c.page_from IS NULL THEN '' ELSE ';page=' || c.page_from END ||
       ';chunk=' || c.chunk_id,
       COALESCE(c.event_date, substr(c.known_at, 1, 10)),
       COALESCE(c.event_date, substr(c.known_at, 1, 10)),
       c.body, 'text', c.known_at, 'chunks_v3.chunk#' || c.chunk_id
FROM chunks_v3.chunk c
JOIN pilot_universe u ON u.isin = c.isin
WHERE c.body IS NOT NULL AND c.isin IS NOT NULL;

-- ---------------------------------------------------------------------------
-- macro: the pilot's series are the World Bank commodity vintage, the F&O bhavcopy
-- and the dated observation panel.  entity_id is the series/underlying identity, not
-- an ISIN (the registry's boilerplate entity_key does not fit macro atoms).
-- ---------------------------------------------------------------------------
INSERT INTO fact
SELECT d.series_code, 'macro.commodity_close', 'commodity=' || COALESCE(d.dim_id, ''),
       d.period_start, COALESCE(d.period_end, d.period_start), d.value, d.unit, d.known_at,
       'market_state_b.series_observation'
FROM market_state_b.series_observation d
WHERE d.kind = 'commodity' AND d.value IS NOT NULL;

INSERT INTO fact
SELECT o.series_code, 'macro.series',
       'dim_id=' || COALESCE(o.dim_id, '') || ';kind=' || COALESCE(o.kind, ''),
       o.period_start, COALESCE(o.period_end, o.period_start), o.value, o.unit, o.known_at,
       'market_state_b.series_observation'
FROM market_state_b.series_observation o
WHERE o.value IS NOT NULL;

-- macro.oi lives in the separate attached side file (fact_oi.sql): 16.2 M contract
-- rows are ~2 GB of what would otherwise be a 2.3 GB core store.  Readers attach the
-- side file as ``oi`` and read ``fact`` UNION ALL ``oi.fact``.

DROP TABLE IF EXISTS _map;

-- ---------------------------------------------------------------------------
-- the screen path the executor uses (one atom across entities in a window).
-- The point lookup needs no index: it walks the table's primary key.
-- ---------------------------------------------------------------------------
CREATE INDEX ix_fact_atom_period ON fact(atom, period_end);
ANALYZE main;   -- never bare ANALYZE: the attached pilot stores are read-only
