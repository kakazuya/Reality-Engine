-- =============================================================================
-- fact_oi.sql - the F&O open-interest side file (QUERY_V4_DESIGN §B.1, §F.6).
--
-- macro.oi is one row per (isin, date, expiry, strike, option type): 16.2 M rows,
-- about 2 GB of what would otherwise be a 2.3 GB core store.  Keeping it in its own
-- attached database keeps the core store small while preserving the atom exactly:
-- same table shape, same key, same values, same known_at convention.
--
-- Rebuild with build_membership.py, which attaches this file as ``oi`` next to the
-- core store.  A reader that needs macro.oi attaches both files:
--
--     ATTACH 'fact_v4_pilot.db'    AS core;
--     ATTACH 'fact_v4_pilot_oi.db' AS oi;
--     SELECT * FROM (SELECT * FROM core.fact UNION ALL SELECT * FROM oi.fact)
--      WHERE atom = 'macro.oi';
--
-- Apply to a build DB that has the pilot stores attached (same aliases as
-- build_membership.py) and the seed table pilot_universe(isin, symbol).
-- =============================================================================

DROP TABLE IF EXISTS fact;
CREATE TABLE fact(
    entity_id    TEXT NOT NULL,
    atom         TEXT NOT NULL,
    dims         TEXT NOT NULL DEFAULT '',
    period_start TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    value,
    unit         TEXT,
    known_at     TEXT NOT NULL,
    source_ref   TEXT NOT NULL,
    PRIMARY KEY (entity_id, atom, dims, period_start, period_end)
) WITHOUT ROWID;

INSERT INTO fact
SELECT f.isin, 'macro.oi',
       'expiry=' || COALESCE(f.expiry, '') ||
       ';option_type=' || COALESCE(f.option_type, '') ||
       ';strike=' || COALESCE(CAST(f.strike AS TEXT), ''),
       f.date, f.date, f.oi, 'contracts', f.date || 'T23:59:59',
       'market_state_b.fno_oi_daily'
FROM market_state_b.fno_oi_daily f
WHERE f.oi IS NOT NULL AND f.isin IS NOT NULL
  AND f.isin IN (SELECT isin FROM pilot_universe);

CREATE INDEX ix_fact_atom_period ON fact(atom, period_end);
ANALYZE main;
