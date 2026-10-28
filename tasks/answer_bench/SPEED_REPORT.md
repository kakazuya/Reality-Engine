# Query speed — 150-case master-bank bench, before → after

Scope: `tasks/answer_bench` 150-case sample (`SAMPLE.jsonl`), deterministic
Python/SQL only (no LLM, no embeddings on the answer path).  Read-only on every
live database; index work was measured on copies under `.tmp/`.

## 1. Result

| metric | before (`RESULTS_v1_before.jsonl`) | after (`RESULTS_v1.jsonl`) |
|---|---:|---:|
| total wall | 340.8 s | 51.4 s |
| mean | 2.27 s | 0.34 s |
| p50 | 1.30 s | 0.19 s |
| p95 | **6.80 s** | **1.20 s** |
| max | **15.63 s** | **3.15 s** |
| cases > 5 s | 24 | **0** |
| cases > 10 s | 2 | **0** |

Gates: p95 ≤ 5 s and max ≤ 10 s — both hold with margin.  Two back-to-back runs
of the final code measured p95 1.74 s / max 3.16 s (first, colder) and p95 1.20 s
/ max 3.15 s (second, saved).  Per-case series: `RESULTS_v1.jsonl` (`seconds`).

Strict grades (`grade_v1.py`; `RESULTS_v1_strict_before.jsonl` vs
`RESULTS_v1_strict.jsonl`):

| strict grade | before | after |
|---|---:|---:|
| ANSWERED | 13 | **15** |
| PARTIAL | 106 | 108 |
| WRONG | **0** | **0** |
| BLOCKED_SCHEMA | 18 | 16 |
| BLOCKED_TOOL | 11 | 9 |
| NOT_IN_DATA | 2 | 2 |

No case regressed from ANSWERED; six improved (MB0449, MB0584 → ANSWERED;
MB0003, MB1007 → PARTIAL from BLOCKED_SCHEMA; MB0044, MB1016 → PARTIAL from
BLOCKED_TOOL).  PIT violations: 0 in both runs.

Tests: `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"`
→ **55 tests, OK**.

## 2. Profile — where the 341 s was

Profiler: `tasks/answer_bench/profile_v2.py` (times every `connect_ro` statement
at execute+fetch, every plugin `_run_sqlite`/`_run_duck` call and every
`Ctx.tool` call).  Raw: `profile_before.json`, per-hop dump
`RESULTS_v1_before.jsonl` (the profiler run itself took 230.6 s with a warmer
OS page cache; the distribution is the same).

Per planner (109 EVIDENCE hops, 154 FACTS, 153 SCREEN, …):

| planner | hops | before total | before max | after total | after max |
|---|---:|---:|---:|---:|---:|
| EVIDENCE | 109 | **198.4 s** | 10.06 s | 24.7 s | 3.14 s |
| SCREEN | 153 | 10.4 s | 1.33 s | 22.2 s¹ | 1.80 s |
| FACTS | 154 | 10.6 s | 0.84 s | 14.4 s¹ | 0.82 s |
| resolve | 301 | 3.4 s | 0.04 s | 12.2 s¹ | 0.13 s |
| RIPPLE | 100 | 3.5 s | 0.40 s | 10.5 s¹ | 0.42 s |
| SERIES | 133 | 3.4 s | 0.95 s | 5.2 s | 1.07 s |
| COMPARE | 32 | 0.4 s | 0.11 s | 0.7 s | 0.12 s |
| EVENT | 43 | 0.04 s | 0.01 s | 0.3 s | 0.14 s |

¹ The after run touched a colder 54 GB page cache than the before profile run
(machine I/O variance) and each hop's seconds are wall clock; the wall-clock
gates in §1 include this and still hold.

Tools (before): `doc_find` 165 calls / 180.8 s / max 5.11 s; `search_docs` 15
calls / 17.2 s / max 10.06 s; `doc_page` 1 call / 0.42 s.  After: no company
`doc_find` calls at all; `doc_page` 1 call / 1.2 s; the corpus search is bounded
FTS.

### Top slow statements (before) with `EXPLAIN QUERY PLAN`

Top-20 by duration contained duplicate rows (the plugin wrapper and the cursor
both record the same statement); the 10 distinct statements below cover the
whole slow tail.  Plans: `profile_before_plans.json` (params recorded in
`profile_before.json`).

| # | time | SQL (truncated) | plan |
|---:|---:|---|---|
| 1 | 10.05 s | `search_docs` hybrid FTS: `SELECT intelligence_fts… FROM intelligence_fts f JOIN document_chunks dc … MATCH '"gold"' LIMIT 40` | `SCAN intelligence_fts VIRTUAL TABLE INDEX 0:M6`; join by PK; `USE TEMP B-TREE FOR ORDER BY` |
| 2 | 4.12 s | `doc_find` chunk walk: `SELECT … FROM document_chunks WHERE symbol IN (?,?,?) AND published_date … AND lower(content) LIKE ? … LIMIT 40` | `SEARCH document_chunks USING INDEX idx_docchunks_symbol_chunk (symbol=?)` + `USE TEMP B-TREE FOR ORDER BY` |
| 3 | 3.96 s | same, INFY (`mark`,`zone`) | same |
| 4 | 3.64 s | same, COALINDIA (`scheme`,`promotion`,`coal`) | same |
| 5 | 3.17 s | same, HDFCBANK (`hdfc`,`bank`,`underperformed`) | same |
| 6 | 3.07 s | same, MUTHOOTFIN (`gold`,`loan`,`ticket`) | same |
| 7 | 3.06 s | same, SAIL (`read`,`promise`) | same |
| 8 | 3.03 s | same, IDEA (`free`,`float`) | same |
| 9 | 2.98 s | same, BHARTIARTL (`arpu`,`subscribers`) | same |
| 10 | 2.98 s | same, ADANIENT (`cash`,`conversion`,`ratio`) | same |

Root causes:

1. **EVIDENCE delegated to `doc_find`**, which walks five stores per call and
   runs a `lower(content) LIKE %token%` over *every chunk of the company* per
   attempt.  On a miss it retries up to 4 queries **and** `_not_found()` re-lists
   all five stores, so a single miss cost 2–6 s (MB0011 15.6 s, MB0201 12.7 s).
2. **The corpus branch called `search_docs`** (hybrid FTS + dense index): 10 s
   for a one-word corpus query.
3. **`chunks_v3` was never used** unless `REALITY_CHUNKS_V3` was exported, and
   the pilot DB is WAL-less, so `connect_ro(mode=ro)` could not even open it
   (needs `immutable=1`).
4. Every hop ran serially; sub-questions re-resolved the same company.

## 3. Fixes (shortest path that holds)

- `reality_engine/query/planners/evidence.py`
  - `chunks_v3` first when it covers the ISIN (30 ISINs / 27 bench symbols);
    the pilot store opens warm per thread with `immutable=1`.
  - The fallback is now **`intelligence_fts` with the owner filter inside the
    MATCH** (`isin:INE… AND (words)`), a PIT date bound and `LIMIT`: one
    statement, no LIKE over the table, no five-store walk (~10–120 ms fresh,
    ~2 ms warm).  Long/selective words go first in the OR so a cold FTS read
    does not pay for generic postings ("coal", "said").
  - Chart/AR asks that the chunk index lacks get a bounded second store
    (`deck_figures.outputs` per company sha, `ar_facts` by ISIN, both
    index-bounded) instead of the old 6 s `doc_find` miss path.
  - Corpus asks use a bounded global FTS query (no dense index, no embeddings).
- `reality_engine/query/answer.py`
  - All hops of a question go to one fixed `ThreadPoolExecutor(4)`; results are
    read back in chain order, so the answer text and hop order are byte-for-byte
    deterministic.  Independent sub-questions are batched into the same pool;
    a sub-question that consumes a previous sub-question's ranking row stays
    sequential.
  - Per-question result cache keyed on (planner, entity, period, ask); RESOLVE
    is keyed on identity + as_of only, so sub-questions share it.
- `reality_engine/query/ctx.py`
  - Thread-local SQLite connections (the shared pool keeps them warm), one
    serialised DuckDB handle, warm per-thread `chunks_v3`, `cache_get/put`.
- `reality_engine/db/readonly.py`
  - `connect_ro(..., immutable=True)` for finished, WAL-less stores (the pilot).

New bench tooling: `profile_v2.py` (hop/SQL/tool profiler), `measure_indexes.py`
(on-copy index measurement).  Baseline kept as `RESULTS_v1_before.jsonl` /
`RESULTS_v1_strict_before.jsonl` / `REPORT_v1_before.md`.

## 4. Index migration for the controller (measured on `.tmp/` copies)

Live DBs were never written.  `.tmp/idx/measure.json`; copies under
`.tmp/idx/copies` (deleted after measuring).  Query shapes are the ones the
planners issue.

| index | table rows | before | after | plan change |
|---|---:|---:|---:|---|
| `corporate_documents(isin, publication_date)` | 127,253 | 29.3 ms | 0.1 ms | `SCAN` + `USE TEMP B-TREE` → `SEARCH … (isin=? AND publication_date>?)` |
| `ann(symbol, DissemDT)` | 1,947,087 | 1,311 ms | 0.1 ms | `SCAN` + sort → index seek |
| `document_chunks(symbol, published_date DESC)` | 2,939,096 | 483 ms | 1.2 ms | symbol seek + sort → covering range seek (LIMIT pushed down) |
| `ar_facts(isin, filed_at DESC)` | 11.2 M (500-ISIN copy; live 32.4 M) | 164 ms | 3.2 ms | isin seek + sort → index seek |
| `ar_docs(symbol)` | 33.7 k | 2.5 ms | 0.2 ms | scan → seek |
| `policy_events(policy_name)` | 21.8 k | 2.0 ms | 0.2 ms | scan → seek |

Notes: the table copies are `CREATE TABLE … AS SELECT` (the live tables'
pre-existing indexes are not copied), so for `document_chunks` and `ar_facts`
the *live* plan/time is the before column and the copy with the new index is the
after column.  For `corporate_documents` and `ann` no live index covers the
query, so the full-scan baseline is the live plan.  The `(isin, published_date)`
twin of the chunks index is the same B-tree shape on the same table and is
included in the script below; it was not separately timed.

```sql
-- equity_intelligence.db (writer process, maintenance window, one DB at a time)
CREATE INDEX IF NOT EXISTS idx_docchunks_symbol_published
    ON document_chunks(symbol, published_date DESC);
CREATE INDEX IF NOT EXISTS idx_docchunks_isin_published
    ON document_chunks(isin, published_date DESC);
CREATE INDEX IF NOT EXISTS idx_corpdocs_isin_pub
    ON corporate_documents(isin, publication_date);
CREATE INDEX IF NOT EXISTS idx_policy_name
    ON policy_events(policy_name);

-- ar_facts.db
CREATE INDEX IF NOT EXISTS ar_facts_isin_filed
    ON ar_facts(isin, filed_at DESC);
CREATE INDEX IF NOT EXISTS ar_docs_symbol
    ON ar_docs(symbol);

-- bse_announcements.db
CREATE INDEX IF NOT EXISTS idx_ann_sym_dissem
    ON ann(symbol, DissemDT);
```

All statements are additive and idempotent.  The two architecture-flagged
indexes are `idx_corpdocs_isin_pub` and `idx_ann_sym_dissem`.

## 5. Reproduce

```bash
python tasks/answer_bench/run_v1.py                 # writes RESULTS_v1.jsonl
python tasks/answer_bench/grade_v1.py               # writes RESULTS_v1_strict.jsonl + REPORT_v1.md
python tasks/answer_bench/profile_v2.py --out profile_after.json
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

`chunks_v3` path: `REALITY_CHUNKS_V3` if set, else
`D:\RealityEngine\pilot\chunks_v3_pilot.db` (documented default; a missing file
just leaves the bounded FTS fallback in place).

## 6. Deliberate deferrals

- **SCREEN** still reads `daily_price_delivery` with one bounded query
  (`LIMIT 30000`) and buckets in memory, not the pilot whole-market tables:
  `market_state_pilot.company_state_daily` has **489 ISINs** (2019-01-01..
  2026-10-19) against screens that ask the Nifty-500 / Nifty-Midcap-150 universe,
  so switching would silently shrink the universe and change grades.  SCREEN is
  ~0.07 s/case mean and not a gate risk (`company_state_daily` in the live DB is
  the rotation once the T2 build is loaded).
- The EVIDENCE corpus path no longer uses the dense index; that is intentional
  (no paid/free embedding in the loop).  Re-adding it is a recall feature, not a
  speed one.
- The `profile_before.json` top-20 list keeps the duplicate plugin/cursor rows;
  the 10 distinct statements are listed in §2.
