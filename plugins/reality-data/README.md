# reality-data — MCP data-search server

One call to learn where the data lives, a few calls to answer a company
question. Read-only by construction: the DuckDB snapshot is opened with
`read_only=True`; every SQLite connection is `mode=ro` + `PRAGMA query_only=ON`.
Every result carries provenance, and AGENTS.md rule 13 (quarantine) is applied.

## Tools

| Tool | Purpose |
|---|---|
| `catalog(refresh=False, db=None, query=None, store=None)` | One line per database; `db='<key>'` lists that database's tables (description, key columns, row count, coverage); `query='<word>'` searches table names/descriptions. Merges `catalog_descriptions.yaml`; works without it. A database added to `DB_SPECS` after the shipped cache was written (pilot3, 4 Nov 2026) is introspected on first use. `store=` (a registered pilot3 store's name or path) reads that store; `db='pilot3'` without it lists the registered stores (T-203). |
| `schema(table, db=None, store=None)` | One table's columns + types, row count, indexes, date coverage and three sample key rows. `db='pilot3'` works like any other store; `store=` reads one registered pilot3 store (T-203). |
| `resolve(query)` | Symbol, company name or ISIN → canonical identity, NSE/BSE codes, ISIN/symbol validity windows. PPL → `INE050001010`. |
| `price(symbol, start, end=None, adjusted=False)` | OHLCV, delivery qty/%, traded value; raw and adjusted closes. NSE first, BSE fallback. |
| `facts(symbol, kind=None, period=None, include_model_read=False)` | Segments, financials, KPIs, guidance: filed XBRL `results_xbrl` first; the model-read stores (`ar_facts`, `deck_figures`, `concall_facts` — AI-extracted October 2026, unverified) are withheld unless `include_model_read=True` or `kind` is `ar`/`deck`/`concall`, and every row carries `extraction` (`filed_xbrl` or `model_read`); `model_read_withheld` counts the rows left out. |
| `search_docs(query, symbol=None, doc_types=None, date_from=None, date_to=None, top_k=10, include_model_read=False)` | Hybrid 4096-d vector + FTS over concalls, decks, annual reports, announcements, RBI/PIB/policy docs; degrades to FTS when a provider/key fails and labels each hit `vector`/`fts`/`both`. Annual-report `ar_facts` model-read quotes are withheld unless `include_model_read=True`, then labelled `extraction=model_read`. |
| `sql(query, db)` | Bounded read-only SELECT/WITH escape hatch: one statement, row limit (default 200, max 1000), 5 s timeout, write/DDL keywords rejected. |
| `project_rules(topic=None)` | Shivam's binding rulings from `tasks/RULINGS.md`: no topic returns the section index (name and the first 120 characters of each bullet); a topic returns, whole, every bullet containing all its 3+ letter words, with its section; a miss returns that index and `found=false`. Call it before deciding scope, briefing a worker or reporting. |
| `project_state()` | The live state from `tasks/STATE.md`: `## Now` and `## Next action` always whole, the other sections up to 6,000 characters, plus the ticket card. |
| `pilot3_*` (17 tools) | `pilot3_fact`, `pilot3_kpi`, `pilot3_cells`, `pilot3_fin`, `pilot3_ratio`, `pilot3_holding`, `pilot3_statements`, `pilot3_guidance`, `pilot3_docs`, `pilot3_search`, `pilot3_topic`, `pilot3_semantic`, `pilot3_tech`, `pilot3_sql` (which also takes `symbol=` or `store=`) over the company a registered store holds, plus `pilot3_ratings` (the separate credit-rating rationale store, below) and `pilot3_calc` / `pilot3_calc_catalog` (arithmetic, not company rows). `pilot3_cells` (T-189) serves the page reader's table and chart cells (`page_cell`): value, row label, column header, table title, status and document provenance; `status` is `verified` (position-checked), `unverified` (served and labelled - hiding them collapses recall) or `quarantined` (never served), and `pilot3_fact` falls back to it when no other pilot3 table holds the metric (`source: page_cell`). `pilot3_fact` (T-186) is the one-call answer for a single number: it routes by metric to the preferred financial line / ratio / company-stated KPI / holding category / share count and returns value, unit and scale word, period, basis, as_of used, source {table, doc_key, page, quote}, known_at and, for a computed figure, the formula with its input rows, plus up to three alternatives and `why_this_one`; a miss returns `found:false` with `searched` and `nearest`. `pilot3_fin` defaults to the consolidated statement and labels `basis` on every row; `pilot3_holding` returns every filed shareholding category with `pct` and `pct_basis`, one row per category and quarter, and takes `category=` (government / GoI, FPI, MF, promoter, public, retail, DII) and `quarters=N` for a multi-quarter path (T-165); `pilot3_kpi` resolves the words investors use (NIM / net interest margin, credit cost, cost of funds) and reports `held_quarantined` when the row check hid the only row (T-165); `pilot3_guidance` returns the current target of each metric+target period by default (an older row a later document replaced is dropped and `superseded_rows` says how many; `history=true` returns the whole chain), with `period` accepting `FY27`, `Q2FY27`, `medium_term` or `long_term`; `pilot3_sql(max_chars=400)` cuts text cells at 400 characters by default and widens to a hard cap of 8000 when a long page text or a full quote is asked for. `pilot3_sql(as_of=...)` (T-156, `lookups_pilot3.py` `_as_of_connection`) runs on a private connection where every table with `known_at`, and `doc_page` through its `doc`, is shadowed by a TEMP view holding only rows known by that day (views stored in the file, such as `fin_quarter_current`, still read the full tables; `doc_page_fts` hits must be joined to `doc_page`). `pilot3_semantic` (T-154, `lookups_semantic.py`) ranks one company's pages by cosine against the page vectors `reality_engine.pilot3.embed_test embed` wrote to `embed/` next to the store (`REALITY_PILOT3_EMBED_DIR` overrides), point-in-time on `COALESCE(page.known_at, doc.known_at)`, and reports `coverage` (pool pages vs pages with a vector); a new query text needs `REALITY_DATA_ALLOW_PAID_EMBED=1` + `DEEPINFRA_API_KEY` (process env, else the Windows user variable, since the dsh sandbox strips keys; Nemotron 8B), is cached by hash in `query_cache_8b.json` and logged in `query_spend.jsonl` (both fall back to `./.tmp/semantic_query/` when a sandboxed worker cannot write the embed dir); vectors are read into memory, never memory-mapped, so a running embed can still replace the npy. `pilot3_ratings` (T-139, `lookups_ratings.py`) reads the outside-doc rating-rationale store named by `REALITY_RATINGS_DB` (default `D:/RealityEngine/outside_doc/ratings.db`, built by `python -m reality_engine.ingestion.rating_rationale_load --src <folder> --out <db>`): point in time on `known_at` (the press-release date the rationale was public, never earlier than its index date), it returns every instrument action known by `as_of` (agency, rating date, instrument, rating, outlook, action, amount_crore) and each rationale's key sections verbatim (rationale, strengths, weaknesses, sensitivities/triggers, liquidity, outlook) with agency/url/date provenance; a company outside the store returns `found=false` with `available_symbols`. |

**T-194 (12 Nov 2026)** closes the T-189 "stopped early" tool failures. `pilot3_topic(symbol, topic, as_of,
date_from, date_to, limit)` returns everything on one theme in one call, grouped by document date: statements
verbatim from every call, related guidance / KPI / page-cell / `event` rows, with `counts` matched / shown / cut (at
that version a 20-item reply stayed under 16 kB; T-197 below adds the coverage block and page-text reach and caps
every text reply at 20 kB). `pilot3_search` now tries the exact phrase first, normalises a money amount
("US$2 bn" = "$2 billion" = "2 billion"), ranks the short printing ("2 bn") after the exact one, and always states
"N page(s) match ... k shown" with `pages_matched`, `pages_short`, `pages_like` and the hits grouped by document.
The new `event` table holds one row per announcement event (regulatory inspection with unit / dates / outcome,
buyback, merger, acquisition, dividend); rebuild it with `python -m reality_engine.pilot3.events --out <db>` (the
`events` build part). The pharma topic vocabulary in `reality_engine/pilot3/lexicon/pharma.yaml` is applied by the
statement tagger to companies of that sector family and by `pilot3_topic` to the ask's words;
`python -m reality_engine.pilot3.transcripts --out <db> --profile <profile> --retag` re-tags the stored statements
in place and reports the share of `other` before and after.

**T-197 (12 Nov 2026) makes every text reply a page, never the whole store.** `pilot3_topic`, `pilot3_statements`,
`pilot3_search`, `pilot3_semantic`, `pilot3_cells` and `pilot3_docs` now carry a `coverage` block -- `searched`,
`not_searched` (the sources the tool cannot see, by name; a source is in exactly one of the two lists),
`matched_total`, `shown`, `cut`, `offset`, `documents` (the matching documents with type, date, title, matching
pages and match count; at most `max(limit*3, 10)` by default, the rest summed by type and month and counted in
`documents_not_listed`; `documents=all` lists every one), `hidden_after_as_of` (with the hidden documents and
their dates, inside `coverage` only) and `outside_date_filter` (the matches a
`date_from`/`date_to` excluded). Their one-line `text` starts with that scope and the exact next call. Every text
tool takes `offset=` to read the next page, returns `read_next` (the quoted page and its neighbours, and for a call
the pages that print the same words), and stays under the 20 kB cap by construction (a heavy theme is trimmed in a
fixed order and says what it cut). `pilot3_topic` and `pilot3_statements` also run the phrase-first page-text matcher
over EVERY held document type -- an untagged call page, a deck table, an annual-report note or a filing body comes
back with `match: text` -- and `event` rows carry the document type, title and a `body_excerpt` of the sentences that
state the outcome, observations, classification, impact or amount (`python -m reality_engine.pilot3.events --out
<db>` rebuilds them; a store made before T-197 gains the columns). `pilot3_cells` serves a label-only row with the
values printed beside it (`values`), and `as_of` reports the documents it hid on every document-derived tool.
Measured on copies of `pilot10.db` and `aurobindo.db`: 12 generic themes x 5 companies, matched items 3,976 -> 16,759
(pilot10) and 2,413 -> 5,530 (aurobindo), every doc type reached, max reply 19.1 kB, median topic call 0.27-0.34 s
(`.tmp/T-197_MEASURE.md`). **T-204 (12 Nov 2026)** sizes a `pilot3_topic` page to its items (`max(6 kB, 3 kB x limit)`,
18 kB cap), so a two-item page lists 10 of its documents and names the rest; `pilot3_topic symbol=KEC topic="order
book" limit=2 as_of=2026-10-19` fell from 8.1 kB to 5.9 kB (10 of 49 documents listed, `documents_not_listed` 39),
`hidden_documents` sits in `coverage` only, and a store without `page_cell` names it in `not_searched` only.

**T-203 (12 Nov 2026): one server, every store.** The `pilot3_*` tools no longer need one store per server start.
`REALITY_PILOT3_STORES` names a registry JSON (`D:/RealityEngine/stores.json` by default); `resolve_symbol`, the
first call of every tool, looks the symbol / ISIN / BSE code / name up in the stores IN REGISTRY ORDER and opens
the first store that holds it, read-only, one cached connection per path. A symbol held in several stores is
answered by the first one and the reply's `provenance` says `also_held_in: [<other paths>]`; provenance also names
the store (`store`) and its path. `REALITY_PILOT3_DB` still pins one store (tests, A/B runs) and switches routing
off. `pilot3_sql` takes `symbol=` or `store=` and, with neither, lists the registered stores instead of guessing;
`catalog(db='pilot3')` does the same listing and `schema(..., db='pilot3', store=...)` reads one store. Generate the
registry (the stores are ordered freshest build first, so its rows match the current code; the repo's own
`pilot3.db` is the last fallback):

**T-202 (12 Nov 2026): the reply names the store's schema version.** Every `pilot3_*` provenance block carries
`schema_version` (from `schema_meta`, read once per routed store path); a store older than the server adds
`schema_note` naming its version and the CLI that migrates a copy
(`python -m reality_engine.pilot3.schema --db <store> --status|--migrate`). The read-only server never migrates a
store: a lookup falls back to the older rule for a column its store lacks.

```powershell
python -m reality_engine.scripts.store_registry --scan D:/RealityEngine --out D:/RealityEngine/stores.json
```

A store whose WAL side files are gone (a finished build whose header still says WAL) is opened `immutable=1` only
after the normal `mode=ro` open fails and only when it has no non-empty `-wal`; a store that still has a WAL is
never read immutably. `not_pilot3` replies name every store searched. `python -m reality_engine.scripts.p3ask`
now takes `--db` as optional (pinned) and otherwise routes through the same registry, e.g.
`python -m reality_engine.scripts.p3ask fact symbol=KEC metric=revenue period=FY26`.

`facts` kinds: `segments`, `financials`, `kpis`, `guidance`, `results`, `deck`,
`concall`, `ar`, or free text. `period`: `FY25`, `Q4FY26`, `2025-03-31`, omitted.

## Data map

| Key | File | What it is |
|---|---|---|
| `truth_duckdb` | `reality_engine/data/snapshots/truth_2026-10-19.duckdb` | PIT snapshot: identity, NSE/BSE prices + delivery, events, AR/deck/concall/results facts, policy/PIB. |
| `equity_intelligence` | `.../data/equity_intelligence.db` | 44 GB search layer: raw documents, chunks + embeddings, `intelligence_fts`, corporate docs, price/flow/peer tables. |
| `ar_facts` | `.../data/ar_facts.db` | Annual-report facts (32.4 M rows, indexed `(isin, fiscal_year)`); model-read by AI, unverified, withheld from default `facts()`/`search_docs`. |
| `results_xbrl` | `.../data/results_xbrl.db` | NSE XBRL filings/facts + trading-ISIN map. |
| `deck_figures` | `.../data/deck_figures.db` | Investor-presentation metrics by page, with source URLs; model-read by AI, unverified, withheld from default `facts()`. |
| `concall_facts` | `.../data/concall_facts.db` | Concall guidance/KPI items with quotes; model-read by AI, unverified, withheld from default `facts()`. |
| `bse_announcements` | `.../data/bse_announcements.db` | BSE announcement feed. |
| `pilot3` | `.../data/pilot3/pilot3.db` | The repo's own three-company build (KEC, BAJFINANCE, HINDALCO): dated page text, KPI series, financial lines, ratios, shareholding, statements, guidance, events. Read it through the `pilot3_*` tools; `pilot3_sql` is the bounded escape hatch. Additive since 4 Nov 2026: `catalog(db='pilot3')`, `schema(table, db='pilot3')` and `sql(query, db='pilot3')` all resolve it. Since T-203 it is the last-registered fallback store: `pilot3_*` route to whichever registered store holds the symbol (`REALITY_PILOT3_STORES`); this build also predates T-192, so a company held in a fresher store is answered there. |

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
  `Qwen/Qwen3-Embedding-8B`, query prompt `query_embed.QWEN_INSTRUCT +
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
  `__search_docs`, `__sql`, `__project_rules`, `__project_state`.
- `REALITY_DATA_ROOT` points at the **data directory** (the `search_docs.py`
  contract); `REALITY_DATA_REPO_ROOT` points at the checkout. Both default
  correctly with no environment.
- `REALITY_PILOT3_STORES` names the pilot3 store registry (default
  `D:/RealityEngine/stores.json`, generated by
  `python -m reality_engine.scripts.store_registry --scan D:/RealityEngine`);
  `REALITY_PILOT3_DB` pins a single store instead and switches routing off (T-203).

Backups made before the change on 2026-10-24 (not kept in this checkout; check the profile and repo folders):

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
  `search_docs("PPL segment revenue", include_model_read=True)` therefore
  returns the PPL AR passages via the `ar_facts`/FTS leg with `source="fts"`
  and `extraction="model_read"`; the default call withholds them (T-103). The
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
