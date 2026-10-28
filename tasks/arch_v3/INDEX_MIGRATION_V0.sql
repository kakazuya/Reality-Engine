-- Query-layer v0 — index migration proposals (NOT RUN; read-only worktree).
--
-- Every statement is additive and idempotent.  Run them from a writer process
-- during the nightly maintenance window, one database at a time.
--
-- Measured need (2026-10-28, live DBs):
--   facts ASIANPAINT ar FY27 (a period not filed): 15.5 s -> 3.2 s cold /
--     0.4 s warm after the code fix (symbol fallback no longer scans 32M rows).
--   search_docs company-scoped: 24 s cold -> 1.9 s warm; the cold cost is the
--     vector-index load (search_docs.warm() at server start), not SQL.
--   EXPLAIN QUERY PLAN still shows a TEMP B-TREE for ORDER BY in both passage
--     queries below; these indexes remove that sort and let the date bound be
--     used inside the index.

-- equity_intelligence.db (2.9M document_chunks rows)
CREATE INDEX IF NOT EXISTS idx_docchunks_symbol_published
    ON document_chunks(symbol, published_date DESC);
CREATE INDEX IF NOT EXISTS idx_docchunks_isin_published
    ON document_chunks(isin, published_date DESC);

-- ar_facts.db (32.4M rows; ar_facts_isin is (isin, fiscal_year), so a
-- filed_at-ordered passage search still sorts)
CREATE INDEX IF NOT EXISTS ar_facts_isin_filed
    ON ar_facts(isin, filed_at DESC);
-- the symbol fallback resolves doc ids through ar_docs (34k rows today)
CREATE INDEX IF NOT EXISTS ar_docs_symbol
    ON ar_docs(symbol);

-- equity_intelligence.policy_events (21.8k rows): the RIPPLE trigger filters
-- policy_name/title/sectors with LIKE; this helps the equality-ish path only.
CREATE INDEX IF NOT EXISTS idx_policy_name
    ON policy_events(policy_name);
