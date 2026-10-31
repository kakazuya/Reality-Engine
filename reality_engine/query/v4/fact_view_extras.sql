-- =============================================================================
-- fact_view_extras.sql - the v4 atoms whose source is outside the five pilot files
-- (QUERY_V4_DESIGN §B.1; tasks/dsh_tasks/V4_WP2C_2026-10-31).
--
-- Applied by build_membership.py only when all three extra stores are attached
-- read-only alongside the pilot stores:
--   quarters   .tmp/quarters_pilot60.db   (build_quarters.py: true single quarters)
--   ei         equity_intelligence.db     (policy, index, flow, ETF, insider, SHP)
--   macro      pilot/macro_all.db         (macro_claim + macro_doc)
--
-- Everything here is bounded by the pilot universe or by a small held table; no
-- network and no writes to the attached files.  Where a branch legitimately finds
-- nothing it stays empty and is reported as such (never silently dropped).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- fin.* quarters: the pilot store's `quarter` rows came from stored fact dates,
-- not from the OneD/FourD context (decision log 2026-10-19), so FourD YTD values
-- stamped with quarter dates were stored as quarters.  Replace every affected
-- quarter with the context-aware derivation in quarters.company_quarter_series;
-- a quarter the derivation refuses to make stays empty (counted by the builder).
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS _qmap;
CREATE TABLE _qmap(metric_key TEXT PRIMARY KEY, atom TEXT NOT NULL);
INSERT INTO _qmap(metric_key, atom) VALUES
    ('revenue',       'fin.revenue'),
    ('pat',           'fin.pat'),
    ('eps',           'fin.eps'),
    ('finance_costs', 'fin.interest_expense'),
    ('capex',         'fin.capex');

DELETE FROM fact WHERE atom IN ('fin.revenue', 'fin.pat', 'fin.eps', 'fin.interest_expense',
                                'fin.capex', 'fin.ebitda')
  AND dims LIKE '%period_kind=quarter%';

INSERT INTO fact
SELECT q.isin, m.atom,
       'basis=' || q.basis || ';period_kind=quarter;derived=' || q.derived,
       q.period_end, q.period_end, q.value, q.unit, q.known_at,
       'quarters.company_quarter_series#' || q.metric_key
FROM quarters.company_quarter_series q
JOIN _qmap m ON m.metric_key = q.metric_key
JOIN pilot_universe u ON u.isin = q.isin
WHERE q.value IS NOT NULL;

-- fin.ebitda for the clean quarters: pbt + finance_costs + depreciation, all three
-- required (a partial sum would understate it), from the same derivations.
INSERT INTO fact
SELECT q.isin, 'fin.ebitda',
       'basis=' || q.basis || ';period_kind=quarter;derived=components',
       q.period_end, q.period_end, SUM(q.value), 'INR_CRORE', MAX(q.known_at),
       'derived:quarters.company_quarter_series:pbt+finance_costs+depreciation'
FROM quarters.company_quarter_series q
JOIN pilot_universe u ON u.isin = q.isin
WHERE q.metric_key IN ('pbt', 'finance_costs', 'depreciation') AND q.value IS NOT NULL
GROUP BY q.isin, q.basis, q.period_end
HAVING COUNT(DISTINCT q.metric_key) = 3;

DROP TABLE IF EXISTS _qmap;

-- ---------------------------------------------------------------------------
-- price.open .. traded_value for the pilot name the NSE panel never carries:
-- INE374E01021 (BMW) has held only a BSE line since 2024-07-01, so the symbol-keyed
-- NSE branches in fact_view.sql cannot fill it.  Fill from the BSE bhavcopy and its
-- delivery file, exchange=BSE, only for an atom that has no NSE row at all (one
-- date is never served from two exchanges in the same series).
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS _bse_only;
CREATE TABLE _bse_only(atom TEXT NOT NULL, isin TEXT NOT NULL, PRIMARY KEY(atom, isin));
INSERT INTO _bse_only
SELECT a.atom, u.isin
FROM (SELECT 'price.open' AS atom UNION ALL SELECT 'price.high' UNION ALL
      SELECT 'price.low' UNION ALL SELECT 'price.volume' UNION ALL
      SELECT 'price.delivery_qty' UNION ALL SELECT 'price.delivery_pct' UNION ALL
      SELECT 'price.traded_value') a
CROSS JOIN pilot_universe u
WHERE NOT EXISTS (SELECT 1 FROM fact f WHERE f.entity_id = u.isin AND f.atom = a.atom)
  AND EXISTS (SELECT 1 FROM ei.mkt_bse_eq_daily e WHERE e.isin = u.isin);

INSERT INTO fact
SELECT e.isin, 'price.open', 'exchange=BSE', e.date, e.date, e.open, 'INR',
       e.date || 'T23:59:59', 'ei.mkt_bse_eq_daily'
FROM ei.mkt_bse_eq_daily e
JOIN _bse_only o ON o.atom = 'price.open' AND o.isin = e.isin
WHERE e.open IS NOT NULL;

INSERT INTO fact
SELECT e.isin, 'price.high', 'exchange=BSE', e.date, e.date, e.high, 'INR',
       e.date || 'T23:59:59', 'ei.mkt_bse_eq_daily'
FROM ei.mkt_bse_eq_daily e
JOIN _bse_only o ON o.atom = 'price.high' AND o.isin = e.isin
WHERE e.high IS NOT NULL;

INSERT INTO fact
SELECT e.isin, 'price.low', 'exchange=BSE', e.date, e.date, e.low, 'INR',
       e.date || 'T23:59:59', 'ei.mkt_bse_eq_daily'
FROM ei.mkt_bse_eq_daily e
JOIN _bse_only o ON o.atom = 'price.low' AND o.isin = e.isin
WHERE e.low IS NOT NULL;

INSERT INTO fact
SELECT e.isin, 'price.volume', 'exchange=BSE', e.date, e.date, e.volume, 'shares',
       e.date || 'T23:59:59', 'ei.mkt_bse_eq_daily'
FROM ei.mkt_bse_eq_daily e
JOIN _bse_only o ON o.atom = 'price.volume' AND o.isin = e.isin
WHERE e.volume IS NOT NULL;

INSERT INTO fact
SELECT e.isin, 'price.traded_value', 'exchange=BSE', e.date, e.date, e.turnover_inr,
       'INR', e.date || 'T23:59:59', 'ei.mkt_bse_eq_daily'
FROM ei.mkt_bse_eq_daily e
JOIN _bse_only o ON o.atom = 'price.traded_value' AND o.isin = e.isin
WHERE e.turnover_inr IS NOT NULL;

INSERT INTO fact
SELECT e.isin, 'price.delivery_qty', 'exchange=BSE', e.date, e.date, d.deliverable_qty,
       'shares', e.date || 'T23:59:59', 'ei.mkt_bse_delivery_daily'
FROM ei.mkt_bse_eq_daily e
JOIN ei.mkt_bse_delivery_daily d ON d.sc_code = e.sc_code AND d.date = e.date
JOIN _bse_only o ON o.atom = 'price.delivery_qty' AND o.isin = e.isin
WHERE d.deliverable_qty IS NOT NULL;

INSERT INTO fact
SELECT e.isin, 'price.delivery_pct', 'exchange=BSE', e.date, e.date, d.delivery_pct,
       '%', e.date || 'T23:59:59', 'ei.mkt_bse_delivery_daily'
FROM ei.mkt_bse_eq_daily e
JOIN ei.mkt_bse_delivery_daily d ON d.sc_code = e.sc_code AND d.date = e.date
JOIN _bse_only o ON o.atom = 'price.delivery_pct' AND o.isin = e.isin
WHERE d.delivery_pct IS NOT NULL;

DROP TABLE IF EXISTS _bse_only;

-- ---------------------------------------------------------------------------
-- macro.policy: one row per extracted policy event that carries a monetary amount.
-- entity_id is the policy identity (not an ISIN: a policy is not a company); the
-- event id keeps the key unique.  known_at is the event's publication stamp.
-- ---------------------------------------------------------------------------
INSERT INTO fact
SELECT 'policy:' || COALESCE(NULLIF(trim(p.policy_name), ''), p.title, 'event-' || p.id),
       'macro.policy',
       'event_id=' || p.id ||
       ';direction=' || replace(COALESCE(p.direction_for_industry, ''), ';', ',') ||
       ';instrument=' || replace(COALESCE(p.instrument, ''), ';', ','),
       substr(p.published_at, 1, 10), substr(p.published_at, 1, 10),
       p.amount_inr_crore, 'INR_CRORE', p.published_at, 'ei.policy_events'
FROM ei.policy_events p
WHERE p.amount_inr_crore IS NOT NULL AND p.published_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- macro.claim: the extracted claim layer (direction is the value; policy type and
-- instrument are dims).  known_at comes from the claim, else from its document.
-- ---------------------------------------------------------------------------
INSERT INTO fact
SELECT 'claim:' || c.claim_id, 'macro.claim',
       'policy_type=' || replace(COALESCE(c.policy_type, ''), ';', ',') ||
       ';instrument=' || replace(COALESCE(c.instrument, ''), ';', ',') ||
       ';doc=' || c.doc_id,
       COALESCE(c.effective_date, substr(COALESCE(c.known_at, d.known_at), 1, 10)),
       COALESCE(c.effective_date, substr(COALESCE(c.known_at, d.known_at), 1, 10)),
       c.direction, 'direction',
       COALESCE(c.known_at, d.known_at), 'macro_all.macro_claim'
FROM macro.macro_claim c
LEFT JOIN macro.macro_doc d ON d.doc_id = c.doc_id
WHERE COALESCE(c.known_at, d.known_at) IS NOT NULL;

-- ---------------------------------------------------------------------------
-- macro.index_close: the NSE index level panel (entity = index name, not an ISIN).
-- ---------------------------------------------------------------------------
INSERT INTO fact
SELECT i.index_name, 'macro.index_close', 'exchange=NSE',
       i.date, i.date, i.close, 'points', i.date || 'T23:59:59',
       'ei.mkt_nse_index_daily'
FROM ei.mkt_nse_index_daily i
WHERE i.close IS NOT NULL;

-- ---------------------------------------------------------------------------
-- macro.flow: one row per date and measure (FII / DII cash net, Rs crore).  The
-- source is date-only, so known_at is end of that day.
-- ---------------------------------------------------------------------------
INSERT INTO fact
SELECT 'fii_dii_cash', 'macro.flow', 'measure=fii_net', f.date, f.date, f.fii_net_cr,
       'INR_CRORE', f.date || 'T23:59:59', 'ei.mkt_fii_dii_cash'
FROM ei.mkt_fii_dii_cash f
WHERE f.fii_net_cr IS NOT NULL
UNION ALL
SELECT 'fii_dii_cash', 'macro.flow', 'measure=dii_net', f.date, f.date, f.dii_net_cr,
       'INR_CRORE', f.date || 'T23:59:59', 'ei.mkt_fii_dii_cash'
FROM ei.mkt_fii_dii_cash f
WHERE f.dii_net_cr IS NOT NULL;

-- ---------------------------------------------------------------------------
-- macro.etf_premium: ETF premium/discount versus iNAV.  The pilot universe is 60
-- operating companies, so this fills the atom market-wide and adds no pilot ISIN.
-- ---------------------------------------------------------------------------
INSERT INTO fact
SELECT e.isin, 'macro.etf_premium',
       'underlying=' || replace(COALESCE(e.underlying, ''), ';', ','),
       e.date, e.date, e.premium_vs_inav_pct, '%', e.date || 'T23:59:59',
       'ei.etf_inav'
FROM ei.etf_inav e
WHERE e.premium_vs_inav_pct IS NOT NULL;

-- ---------------------------------------------------------------------------
-- hold.fpi_limit_utilised: from the shareholding XBRL view.  Held for 0 of the 60
-- pilot ISINs (40 shareholding XBRL files market-wide) - the branch stays wired.
-- ---------------------------------------------------------------------------
INSERT INTO fact
SELECT s.isin, 'hold.fpi_limit_utilised', '', s.quarter_end, s.quarter_end,
       s.fpi_limit_utilised_pct, '%',
       COALESCE(s.broadcast_at, s.quarter_end || 'T23:59:59'), 'ei.shareholding'
FROM ei.shareholding s
JOIN pilot_universe u ON u.isin = s.isin
WHERE s.fpi_limit_utilised_pct IS NOT NULL;

-- ---------------------------------------------------------------------------
-- flows.net_inr: the pilot's event_leakage_window is empty, so the atom is filled
-- from the held insider disclosures instead: net buy value per ISIN and disclosure
-- day (acquisition/purchase positive, everything else negative), known_at = the
-- latest intimation in that day's net.  Superseded rows are excluded.
-- ---------------------------------------------------------------------------
INSERT INTO fact
SELECT i.isin, 'flows.net_inr', 'flow_kind=insider',
       substr(i.known_at, 1, 10), substr(i.known_at, 1, 10),
       SUM(CASE WHEN lower(COALESCE(i.transaction_type, '')) LIKE '%acq%'
                  OR lower(COALESCE(i.transaction_type, '')) LIKE '%buy%'
                  OR lower(COALESCE(i.transaction_type, '')) LIKE '%purchase%'
                THEN i.value_inr ELSE -i.value_inr END),
       'INR', MAX(i.known_at), 'ei.insider_trades_v2'
FROM ei.insider_trades_v2 i
JOIN pilot_universe u ON u.isin = i.isin
WHERE i.value_inr IS NOT NULL AND i.known_at IS NOT NULL
  AND COALESCE(i.is_superseded, 0) = 0
GROUP BY i.isin, substr(i.known_at, 1, 10);

ANALYZE main;
