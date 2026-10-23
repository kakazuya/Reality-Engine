# reality-data — MCP data-search server

One call to learn where the data lives, a few calls to answer a company
question. Read-only by construction: the DuckDB snapshot is opened with
`read_only=True`; every SQLite connection is `mode=ro` + `PRAGMA query_only=ON`.
Every result carries provenance, and AGENTS.md rule 13 (quarantine) is applied.

## Tools

| Tool | Purpose |
|---|---|
| `catalog(refresh=False)` | Every database, table, one-line description, key columns, row count, date coverage. Merges `catalog_descriptions.yaml`; works without it. |
| `resolve(query)` | Symbol, company name or ISIN → canonical identity, NSE/BSE codes, ISIN/symbol validity windows. PPL → `INE050001010`. |
| `price(symbol, start, end=None, adjusted=False)` | OHLCV, delivery qty/%, traded value; raw and adjusted closes. NSE first, BSE fallback. |
| `facts(symbol, kind=None, period=None)` | Segments, financials, KPIs, guidance from `ar_facts`, `results_xbrl`, `deck_figures`, `concall_facts`, with doc/page/period/basis/quote. |
| `search_docs(query, symbol=None, doc_types=None, date_from=None, date_to=None, top_k=10)` | Hybrid 4096-d vector + FTS over concalls, decks, annual reports, announcements, RBI/PIB/policy docs; degrades to FTS when a provider/key fails and labels each hit `vector`/`fts`/`both`. |
| `sql(query, db)` | Bounded read-only SELECT/WITH escape hatch: one statement, row limit (default 200, max 1000), 5 s timeout, write/DDL keywords rejected. |

`facts` kinds: `segments`, `financials`, `kpis`, `guidance`, `results`, `deck`,
`concall`, `ar`, or free text. `period`: `FY25`, `Q4FY26`, `2025-03-31`, omitted.

## Data map

| Key | File | What it is |
|---|---|---|
| `truth_duckdb` | `reality_engine/data/snapshots/truth_2026-10-19.duckdb` | PIT snapshot: identity, NSE/BSE prices + delivery, events, AR/deck/concall/results facts, policy/PIB. |
| `equity_intelligence` | `.../data/equity_intelligence.db` | 44 GB search layer: raw documents, chunks + embeddings, `intelligence_fts`, corporate docs, price/flow/peer tables. |
| `ar_facts` | `.../data/ar_facts.db` | Annual-report facts (32.4 M rows, indexed `(isin, fiscal_year)`). |
| `results_xbrl` | `.../data/results_xbrl.db` | NSE XBRL filings/facts + trading-ISIN map. |
| `deck_figures` | `.../data/deck_figures.db` | Investor-presentation metrics by page, with source URLs. |
| `concall_facts` | `.../data/concall_facts.db` | Concall guidance/KPI items with quotes. |
| `bse_announcements` | `.../data/bse_announcements.db` | BSE announcement feed. |

`catalog_cache.json` ships measured row counts/coverage for 218 tables (the
curated YAML covers 224; demo/placeholder/archive/FTS-shadow tables are
excluded). Rebuild with:

```powershell
C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe plugins/reality-data/server/catalog.py --refresh
```

## Search index: which one is current

Read from the meta files and the re-embed code:

| Index | Rows | Dim | Tiers | Status |
|---|---:|---:|---|---|
| `vector_index` (bge-small) | 1,714,861 | 384 | all | **stale**: built 2026-09-30 from 2,035,471 chunks; the corpus now has 2,260,570 chunks. |
| `vector_index_qwen8b` | 340,887 | 4096 | 0–2 | complete, **superseded** by Nemotron-8B for these tiers. |
| `vector_index_nemotron8b` | 340,887 | 4096 | 0–2 | **current**: complete; 51-question test hit@5 94.1%. |
| `vector_index_qwen8b_ar` | 1,367,706 | 4096 | 3 (annual reports) | **current**: complete. |

So the current *indexes* are **Nemotron-8B for transcripts/decks/macro
(tiers 0–2) + Qwen3-8B for annual reports (tier 3)**. `query_embed.py` makes
them queryable:

- `nemotron8b`: DeepInfra OpenAI-compatible `/embeddings`, model
  `nvidia/Nemotron-3-Embed-8B`, query prompt `"query: " + question`, key
  `DEEPINFRA_API_KEY`.
- `qwen8b_ar`: Nebius `/embeddings` (tokenfactory, studio fallback), model
  `Qwen/Qwen3-Embedding-8B`, query prompt `embed_model_test.QWEN_INSTRUCT +
  question`, key `NEBIUS_API_KEY`.
- Both return normalised float32 4096-d vectors and are LRU-cached (256
  entries, 10 s timeout, one retry); a missing key raises
  `MissingAPIKeyError` so `search_docs` falls back to FTS honestly.
- **qwen8b_ar coverage: 61,440 / 1,367,706 rows done (`done.npy`), 4.49%.**
  Only done rows are searched. `catalog()` reports this under `indexes`.
- Search is exact cosine over done rows after a 512-d candidate pass
  (compact cache under `server/.cache/`, gitignored); a full 4096-d scan of
  Nemotron does not fit in this box's free RAM. The final rerank is exact.

Known local state: the Nemotron/DeepInfra key works (live smoke 1.9–2.4 s per
fresh query; LRU-cached repeats are milliseconds). The `NEBIUS_API_KEY` is
present but currently rejected with HTTP 401 by both Nebius endpoints, so the
tier-3 dense leg falls back to FTS until a valid key is installed.

## Registration

- Claude / root: `.mcp.json` → server `reality-data` (absolute Python + script paths).
- dsh `headless` and `web` profiles: `cordis.patch.yml` inserts
  `mcp-reality-data` (`@deepseek-ai/dsh-mcp-client`, stdio). Tool names are
  `mcp__reality-data__catalog`, `__resolve`, `__price`, `__facts`,
  `__search_docs`, `__sql`.
- `REALITY_DATA_ROOT` points at the **data directory** (the `search_docs.py`
  contract); `REALITY_DATA_REPO_ROOT` points at the checkout. Both default
  correctly with no environment.

Backups made before the change:

```text
.mcp.json.bak-20261024
~/.dsh/profiles/headless/cordis.patch.yml.bak-20261024-reality-data
~/.dsh/profiles/web/cordis.patch.yml.bak-20261024-reality-data
```

The existing `*.bak-20261024` profile backups were left untouched so earlier
states are not destroyed. A running Codex/Claude/dsh host must restart to pick
up a newly registered MCP server.

## Run / test

```powershell
# stdio server (normally launched by the host)
C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe plugins/reality-data/server/server.py

# unit + MCP stdio tests
C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe -m unittest discover -s plugins/reality-data/tests -p "test_*.py" -v

# end-to-end acceptance (prints measured latencies)
C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe plugins/reality-data/tests/acceptance_check.py

# one live embedding call per provider + ranking check
C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe plugins/reality-data/tests/embed_smoke.py
```

## Known gaps

- PPL has **no chunk** in either 4096-d index: `document_chunks` holds 0
  PPL rows (PPL annual reports live only in `ar_facts`, quote + page).
  `search_docs("PPL segment revenue")` therefore returns the PPL AR passages
  via the `ar_facts`/FTS leg with `source="fts"`, not a vector hit. The
  ranking check uses a known pipe-sector concall chunk (rank 1) and reports
  the PPL absence. Making PPL vector-searchable requires chunking/embedding
  its ARs — an explicit re-embedding decision, not done here.
- `NEBIUS_API_KEY` is rejected (HTTP 401) by both Nebius endpoints, so
  `qwen8b_ar` dense search is currently inactive; FTS still serves tier 3.
- `price` reads the 2026-10-19 snapshot. The live SQLite `daily_price_delivery`
  may have newer rows; snapshot choice is explicit in every provenance block.
- `facts` uses the indexed live SQLite fact stores. The snapshot copies are
  available through `sql(db="truth")`.
- Quarantine currently excludes annual-report doc `92565` (wrong-company PDF),
  the three `*_demo` tables, and synthetic `INE_AUTO*` ISINs from `resolve`.
