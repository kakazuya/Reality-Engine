# Speed plan — 20 timed queries across every planner

Method: read-only connections (`reality_engine.db.readonly.connect_ro`, `mode=ro`,
`query_only=1`), `EXPLAIN QUERY PLAN` first, then 3–5 runs and the median. SQLite timings are
wall-clock inside the process; DuckDB timings are the same measure on the dated snapshot. Where a
table does not exist yet, `SCHEMA_V3.sql` was executed into `.tmp/proto.db` and filled with
**10,000 synthetic rows per table** (deterministic seed 7, no production rows copied). Raw output:
`.tmp/speed_live.json`, `.tmp/speed_duck.json`, `.tmp/speed_proto.json`, `.tmp/speed_dense` (stdout),
`.tmp/proto.db`.

Machine: the same box the pilot runs on; DB files on the C: drive, cold cache for the live queries.

---

## 1. The 20 representative queries — measured

| # | planner | query | index / plan | measured |
|---|---|---|---|---:|
| 1 | RESOLVE | symbol → ISIN valid on 2026-10-19 | `idx_sih_symbol (symbol, first_date)` | **0.02 ms** |
| 2 | SERIES | price+delivery+RSI range, 1 ISIN, 10 months | `idx_daily_isin_date (isin,date>` | **0.26 ms** |
| 3 | FACTS | last 8 XBRL filings for an ISIN | `ix_filings_isin (isin=?)` | **0.13 ms** |
| 4 | FACTS | one filing × one concept (SegmentRevenue) | `ix_facts_file_concept (file,concept)` | **0.13 ms** |
| 5 | FACTS | AR facts by ISIN + category='segment' | `ar_facts_isin (isin=?)` + category filter | **1.49 ms** |
| 6 | FACTS | concall items by ISIN + list='guidance' | `idx_cc_items_isin (isin=?)` | **0.34 ms** |
| 7 | FACTS | deck facts for an ISIN (join pages on sha256) | `ix_pages_isin (isin=?)` | **6.49 ms** |
| 8 | RIPPLE | policy claims in a window, name LIKE 'tariff' | `idx_policy_pub (published_at range)` | **0.15 ms** |
| 9 | EVIDENCE | FTS5 MATCH 'order book' + isin filter, 2.3M chunks | FTS5 + `chunk` isin filter | **238.06 ms** |
| 10 | SCREEN | top delivery % on one date (turnover floor) | `idx_price_date (date=?)` | **2.31 ms** |
| 11 | SERIES | commodity window (Copper, 2024-05..2026-10) | PK `(date)` autoindex | **0.89 ms** |
| 12 | EVIDENCE | documents for a symbol (doc list) | `idx_docs_sym_date (symbol=?)` | **0.09 ms** |
| 13 | EVENT | events for an ISIN in 2026 (DuckDB snapshot) | DuckDB `events(isin,known_at_utc)` | **5.38 ms** |
| 14 | SERIES | adjusted price range for a symbol (DuckDB) | `px_nse_adj(symbol,date)` | **8.75 ms** |
| 15 | FACTS | AR segment facts for an ISIN (DuckDB) | `ar_facts(isin,category)` | **1.99 ms** |
| 16 | SCREEN | large caps on one date by mcap (prototype) | `ix_csd_date_bucket (date,mcap_bucket)` | **0.09 ms** |
| 17 | SCREEN | index members as of a date (prototype, interval) | `ix_cmp_index_added (index_code,added_on)` | **0.15 ms** |
| 18 | FACTS | segment P&L for an ISIN + period (prototype) | PK `(isin,segment,period_end,metric,basis)` | **0.01 ms** |
| 19 | EVENT | event day0 for an ISIN (prototype) | `ix_ed0_isin_sess (isin,session_0)` | **0.04 ms** |
| 20 | EVIDENCE | FTS + isin + doc_type + known_at filter (prototype, 10k) | FTS5 + `ix_chunk_isin_known` | **16.74 ms** |

**p95 of the 20 = 238 ms** (sorted: 0.01, 0.02, 0.04, 0.09, 0.09, 0.13, 0.13, 0.15, 0.15, 0.26,
0.34, 0.89, 1.49, 1.99, 2.31, 5.38, 6.49, 8.75, 16.74, **238.06**). Both gates hold with margin:
search p95 = 238 ms < 2,000 ms; structured lookups p95 = 5.4 ms < 300 ms.

Search is the only path near a second. Its cost is dominated by the FTS `MATCH` over 2.3M rows,
not by the filters (the isin filter alone is 0.08 ms, Q25). The dense rerank adds 1.62 ms for
2,000 × 4096-d candidates (measured, `measure_dense.py`), i.e. under 1% of the search budget.

---

## 2. Today's two traps (measured, must be fixed before the pilot)

| trap | why | measured | fix | evidence the fix works |
|---|---|---|---:|---|---|
| `bse_announcements.ann WHERE symbol=?` | no index on `symbol`; 1.95M-row scan | **2,423 ms** | `event_day0` (PIT session map) + `CREATE INDEX idx_ann_sym_dissem ON ann(symbol, DissemDT)` | same B-tree shape on `corporate_documents(symbol)` = 0.09 ms (Q27) |
| `corporate_documents WHERE isin=?` | index is `(symbol, date)`; a full 127k-row scan | **220 ms** | `CREATE INDEX idx_corpdocs_isin_pub ON corporate_documents(isin, publication_date)`; v3 reads `chunks_v3.doc(isin, known_at)` | `chunk(isin, known_at)` path = 0.08 ms (Q25, 2.9M rows) |

Both are one-line migrations on the existing DB, not new tables. Neither is in the draft plan, and
either one alone breaks the 2 s gate if an event query runs cold.

Two secondary findings: `ar_facts WHERE isin=? AND item LIKE ?` is 9.6 ms despite the LIKE (the isin
index narrows to the company's facts first — acceptable); `mkt_bse_eq_daily.isin` is only 36% filled,
so any query that joins BSE prices by ISIN must fall back to `sc_code` (7.53M rows, `isin` 2.69M).

---

## 3. Scale caveat for the prototype rows (16–20)

`.tmp/proto.db` holds 10k rows per table, not the full build. A B-tree seek is
`O(log n) + k rows`, so the plan shape is what scales, not the constant; the same shape at live
scale is measured on the tables that already exist:

| proposed table | prototype rows | closest live equivalent | live rows | live time |
|---|---:|---|---:|---:|
| `company_state_daily` (`isin,date` PK, date+bucket index) | 10,000 | `daily_price_delivery` (`isin,date`) | 3,194,632 | 0.26 ms range / 2.31 ms date screen |
| `chunk` + `chunk_fts` (filter then FTS) | 10,000 | `document_chunks` + `intelligence_fts` | 2,939,096 / ~2.3M | 0.08 ms by isin / 238 ms FTS |
| `company_metric_series` | 10,000 | `quarterly_financials(isin,date)` | 15,173 | 0.02 ms |
| `event_day0` | 10,000 | `events` (DuckDB) | 3.3M | 5.38 ms by isin |
| `company_membership_pit` | 1,000 | `index_membership` (one snapshot) | 300 | 0.01 ms |

Full-build row counts and the 13.4M-row upper bound for `company_state_daily` are in
`SCHEMA_V3.sql` (BUILD lines). If the full `company_state_daily` build shows the date screens
slowing past 300 ms, the fix is a covering index `(date, mcap_bucket, isin, traded_value_20d_cr)`,
not a different design.

---

## 4. Query plans that must not appear (asserted in the pilot harness)

The re-run harness captures `EXPLAIN QUERY PLAN` for every query it executes and fails on:

1. `SCAN` of a table above 1,000,000 rows inside a per-case query (Q20's pattern).
2. `USE TEMP B-TREE FOR ORDER BY` on a table above 100,000 rows (a sort of a big result set).
3. Any plan whose text contains `document_chunks` or `ar_facts` without an `isin=`/`doc_id=` seek.
4. Any `SCAN p` in the deck join (must be `ix_pages_isin`).
5. The FTS path must show `VIRTUAL TABLE INDEX 0:M…`; a plain table scan of `chunk` for a text
   query is a defect.

---

## 5. Build-cost summary (what the speed plan assumes exists)

| artefact | rows | build (8 workers) | source |
|---|---:|---:|---|
| `chunks_v3` doc/chunk/tag/FTS | ~150k docs / 3.4M chunks / ~13M tags | ~260 min parse + 3 min FTS + 12 min tags | 78k in-scope docs measured or catalogued (`COVERAGE.md §2`) |
| `company_state_daily` | ≤13.4M | 15 min | `px_daily` 7.3M + shares from XBRL |
| `event_day0` | 3.3M | 6 min | `truth.events` |
| `event_leakage_window` | 6.3M | 25 min | prices + delivery + insider + deals |
| `company_metric_series` | ~910k | 20 min | 13.9M XBRL facts × concept map |
| `company_segment_pnl` | ~35k | 45 min + validation | `ar_facts` segment 145,742 facts |
| `macro_claim` / `_target` | ~60k / 180k | 10 min + 4 h reader | `policy_events` + PIB/budget text |
| membership / sector / theme intervals | ~23k | 10 min + 1 day curation | snapshot + circulars (fetch) |
| reader-filled tables (cost, capacity, orders, price revisions) | 20k–220k each | 2–6 h reader each | concall/deck/AR text |

The reader cost is the real cost of the plan: ~11 reader-filled tables × 2–6 h. The deterministic
tables are all under 30 min. That is why the pilot splits into T1 (reader, 30 ISINs) and T2
(deterministic, 489 ISINs) — see `PILOT_SPEC.md §1`.
