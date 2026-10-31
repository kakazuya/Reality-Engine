-- =============================================================================
-- fact_view_holdings_isin.sql - hold.pct for the pilot names whose shareholding
-- filing still carries an older ISIN (PIDILITIND INE318A01018, GRASIM
-- INE047A01013, HINDALCO, SAIL, HINDPETRO, ...).
--
-- fact_view.sql joins market_state.company_ownership_pit on the pilot ISIN, so a
-- filing recorded under a pre-split ISIN falls out and 21 of the 60 names end up
-- with no holdings row.  This step maps the filing's symbol to the pilot ISIN
-- through the held symbol -> ISIN history and copies the filing's own rows once.
--
-- The source is shp_index, the same store the reality-data ``holding`` tool reads:
-- it carries promoter_pct and public_pct only, so those are the two classes copied.
--
-- Run after fact_view.sql in build_membership.build() with these ATTACH aliases:
--   equity_intelligence  equity_intelligence.db  (shp_index, symbol_isin_history)
--   pilot_universe       seeded by build_membership.seed_universe()
--
-- PIT: known_at is the filing's own broadcast/dissemination time (falling back to
-- its submission date), never the crawl date of the feed.  A filing row with
-- neither timestamp is not copied: a value is not usable before its filing record.
-- INSERT OR IGNORE keeps every row fact_view.sql already built (current ISINs).
-- =============================================================================

DROP VIEW IF EXISTS _shp_latest;
CREATE TEMP VIEW _shp_latest AS
SELECT isin, symbol, quarter_end, promoter_pct, public_pct, known_at
FROM (SELECT s.isin, s.symbol, s.quarter_end, s.promoter_pct, s.public_pct,
             COALESCE(s.broadcast_at, s.submission_date) AS known_at,
             ROW_NUMBER() OVER (
                 PARTITION BY upper(s.symbol), s.quarter_end
                 ORDER BY COALESCE(s.broadcast_at, s.submission_date) DESC) AS rn
      FROM equity_intelligence.shp_index s
      WHERE s.symbol IS NOT NULL AND s.quarter_end IS NOT NULL)
WHERE rn = 1;

INSERT OR IGNORE INTO fact
SELECT u.isin, 'hold.pct', 'holder_class=promoter', s.quarter_end, s.quarter_end,
       s.promoter_pct, '%', s.known_at,
       'equity_intelligence.shp_index#symbol_isin_history'
FROM _shp_latest s
JOIN equity_intelligence.symbol_isin_history h
  ON h.exchange = 'NSE' AND upper(h.symbol) = upper(s.symbol)
JOIN pilot_universe u ON u.isin = h.isin
WHERE s.promoter_pct IS NOT NULL AND s.known_at IS NOT NULL;

INSERT OR IGNORE INTO fact
SELECT u.isin, 'hold.pct', 'holder_class=public', s.quarter_end, s.quarter_end,
       s.public_pct, '%', s.known_at,
       'equity_intelligence.shp_index#symbol_isin_history'
FROM _shp_latest s
JOIN equity_intelligence.symbol_isin_history h
  ON h.exchange = 'NSE' AND upper(h.symbol) = upper(s.symbol)
JOIN pilot_universe u ON u.isin = h.isin
WHERE s.public_pct IS NOT NULL AND s.known_at IS NOT NULL;

DROP VIEW IF EXISTS _shp_latest;
