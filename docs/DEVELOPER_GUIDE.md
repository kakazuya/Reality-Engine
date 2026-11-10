# Developer guide

Moved from `AGENTS.md` on 1 Nov 2026 so agents do not load it at every start; checked against the code on 2 Nov (T-045). Look up code with grep/read, or `code-tools` `outline` for one file's symbols, first.

## 1. System Architecture & Directory Map

Sections 1 and 2A to 2H describe the older research engine, which is still in the repo. The pilot lives in `reality_engine/pilot/`, `reality_engine/query/` and `tasks/pilot60/`: sections 2I to 2K.

```
repo root/
├── reality_engine/
│   ├── db/                 # SQLite (WAL) live databases + FTS5, repository (no PostgreSQL is installed or used)
│   │   ├── schema.sql      # SQLite DDL (live): business_model_profiles, moat_evaluations, geographic_exposure, regulatory_political_risks, raw_documents, document_chunks, macro_events, ripple_effects (self-ref DAG)
│   │   ├── postgres_schema.sql # UNUSED: Postgres DDL kept for reference only; nothing runs on it (countries, industries, companies, business_model_profiles, moat_evaluations, raw_documents, document_chunks ivfflat, macro_events, ripple_effects PN/MN/S, financial_metrics, model_explainer_rankings, lens_activation_log, pruning_decay_config)
│   │   └── repository.py   # Query API & atomic persistence (moat_score GENERATED, ENI, ripple CTE, model rankings, dense substrate promotion)
│   ├── ingestion/          # Multimodal feeds with yt-dlp+Whisper & layout PDF parsing
│   │   ├── master_sync.py  # NSE & BSE scrip list synchronizer (ISIN anchor)
│   │   ├── nse_client.py   # NSE Full Bhavcopy, deliverable volume, PIT insider trades
│   │   ├── bse_client.py   # BSE Bhavcopy, corporate filings, announcements
│   │   ├── fundamentals_client.py # Quarterly/annual financials, balance sheet and solvency metrics (yfinance + BSE/NSE filings)
│   │   ├── financially_free_client.py # Advance/decline & market breadth, with fallback to local NSE index breadth
│   │   ├── headless_fetcher.py # Headless browser takes cookies/JWT for blocked BSE/NSE endpoints, replays them over HTTP; fails closed without Playwright
│   │   ├── macro_pdf_fetcher.py # Budget, PIB and RBI PDFs (cli: fetch-macro, alias fetch-headless)
│   │   ├── telegram_client.py # Thread listener with mock/offline fallback mode
│   │   ├── youtube_transcriber.py # yt-dlp + Whisper (local) + RapidOCR diarization (budget/RBI/Concall MP4), no cloud
│   │   └── pdf_ingestor.py      # Layout-aware PyMuPDF/Marker for Budget/Economic Survey
│   ├── processing/         # Analytics, distillation, ensemble, self-correction & causal reasoning
│   │   ├── technical_engine.py    # Rolling SMAs, RSI(14), delivery spike ratios (cutoff excludes plain noise)
│   │   ├── fundamental_engine.py  # YoY/QoQ revenue & PAT acceleration scores → financial_metrics
│   │   ├── financial_validator.py # Financial figure sanity/validation before dense-substrate promotion
│   │   ├── business_profiler.py   # Builds business_model_profiles archetype/recurrence/pricing_power
│   │   ├── composite_screener.py  # All-peers weighted ensemble ranker (FF5 + quality/policy/supply lenses), NOT top-down-only
│   │   ├── moat_scorer.py         # Moat=0.25*SC+0.25*NE+0.20*CA+0.20*IA+0.10*ES, width/trajectory
│   │   ├── policy_engine.py       # ENI=Severity(±5)×Prob, regulatory_political_risks aggregator
│   │   ├── distillation_engine.py # EAV + JSON business cyclicality & supply chain parameters → DENSE SUBSTRATE
│   │   ├── distillation_pruner.py # Raw→dense promotion + decayed-signal pruning helper
│   │   ├── vision_engine.py       # Multimodal vision-language extraction (slides/charts/tours) → visual_evidence_artifacts
│   │   ├── causal_engine.py       # Recursive CTE ripple_chain: PN=∏Pi, MN=RawN×PN×β, S=|MN|×20/(1+ln(1+Lag))
│   │   ├── macro_simulator.py     # Macro policy shock propagation & impact matrix
│   │   ├── pruning_engine.py      # Raw→dense promotion, decay λ; OWNS prune_decayed_signals(); structural-milestone (is_structural_milestone=1, T½ INF) survival
│   │   ├── ocr_engine.py          # RapidOCR on DirectML or CUDA, else CPU: image & document text extractor
│   │   ├── document_parser.py     # PDF & presentation parser with section chunking → document_chunks (SQLite) + FTS5
│   │   ├── event_graph.py         # Transient event-graph spawner: parse %/date/exceptions, 2nd-order fwd/back supply chain
│   │   ├── ensemble_ranker.py     # Per-stock/sector/geo/time+conditions + investor-majority model_explainer_rankings
│   │   ├── eod_corrector.py       # Continuous self-correction: EOD price+FII/DII+event batch, per-scrip learned noise floor
│   │   ├── substrate_hygiene.py   # Trust layer: quarantines test/demo/synthetic-ISIN rows, reports structural degradation (constant features, template-less policy coverage); owns substrate_quarantine
│   │   └── peer_graph.py          # Analog peer graph: precomputed nearest neighbours over quantified substrate with feature-signal gating, per-pair coverage, drivers and anchor baselines; owns company_peer_graph/company_peer_features/company_peer_runs
│   ├── pipeline/           # End-to-end operational pipelines
│   │   ├── phase1_runner.py       # Ingestion, distillation to dense substrate, and checkpoint audit runner
│   │   ├── backfill.py            # Historical Bhavcopy session backfiller
│   │   ├── panic_monitor.py       # Market drawdown & crisis bargain absorption scanner
│   │   └── inbox_runner.py        # Local inbox PDF/image scanning & indexing → raw_documents
│   ├── search/             # Hybrid lexical & vector retrieval
│   │   └── hybrid_search.py       # legacy search (LanceDB/bge + FTS5); the live search is plugins/reality-data/server/search_docs.py
│   ├── agent/              # High-context AI agent orchestration & deterministic tools
│   │   ├── schemas.py             # Generalized Pydantic lens contracts (MacroEventExtraction, AdjacentPossibleExtraction, VideoIntelligenceExtraction, any lens)
│   │   ├── tools.py               # Deterministic quantitative & causal tools (moat, ENI, ripple CTE, ensemble rank, event-graph)
│   │   └── orchestrator.py        # Multi-lens thesis synthesizer (dense substrate → peer ensemble → transient graph → MoE ranking → correction loop)
│   ├── reporting/          # Multi-format output exporters
│   │   └── writer.py              # JSON, Markdown, and HTML report generator
│   ├── ui/                 # Interactive financial terminal
│   │   └── dashboard.py           # Streamlit 6-tab analytical web application
│   ├── pilot/              # Pilot extraction: extract60.py, proto3.py (section 2I)
│   ├── query/              # Query layer, v4 in query/v4/ (section 2J)
│   ├── scripts/            # Fetchers, loaders, gates and reports, run with python -m reality_engine.scripts.<name>
│   ├── harness/, toolbelt/, tools/ # Test harness, shared helpers, tools/textrec (HP OCR helper)
│   ├── tests/              # Test suite
│   ├── cli.py              # Unified CLI entry point
│   ├── contracts.py        # Typed write contracts for the pilot measures
│   ├── raw_store.py        # Content-addressed raw files; RawStore fetches Drive-only files (T-102)
│   └── config.py           # Paths, PRAGMAs, API headers, and thresholds
├── plugins/                # MCP servers: reality-data, dsh-worker, agy-worker (Antigravity/Gemini coding jobs, T-112; README there) and others
├── machines/               # How to operate each computer
├── tasks/                  # State, rulings, tickets, plans, reports
├── .kilo/
│   ├── command/            # Project slash commands (/test, /bootstrap, /dashboard, etc.)
│   ├── agent/              # Specialized agents (quant-analyst, macro-graph, pipeline-tester)
│   ├── setup-script.ps1    # Agent Manager worktree setup (PowerShell)
│   ├── setup-script.sh     # Agent Manager worktree setup (POSIX)
│   ├── run-script.ps1      # Agent Manager run/dashboard trigger (PowerShell)
│   ├── run-script.sh       # Agent Manager run/dashboard trigger (POSIX)
│   └── kilo.jsonc          # Project configuration & schema
```

## 2. Core Workflows & Operational Commands

### A. Testing & Verification
The full suite reaches 7.5 GB (T-006), so run it on the HP, not the MSI; on the MSI run the module you changed.
```bash
# Run all unit tests
python -m unittest discover -s reality_engine/tests -p "test_*.py"

# Run a specific test module
python -m unittest reality_engine.tests.test_phase1
python -m unittest reality_engine.tests.test_quant_hardening
python -m unittest reality_engine.tests.test_agent_and_reporting
python -m unittest reality_engine.tests.test_cli_and_dashboard
python -m unittest reality_engine.tests.test_derived_substrate
python -m unittest reality_engine.tests.test_peer_graph_and_hygiene
```

### B. Bootstrap & Data Ingestion
Initialize the database, ontologies, and historical market data:
```bash
# 1. Seed dynamic parameter ontologies and canonical causal graph nodes
python reality_engine/cli.py seed-ontologies

# 2. Synchronize master company directory across NSE and BSE
python reality_engine/cli.py sync-master

# 3. Backfill 25 historical Bhavcopy sessions
python reality_engine/cli.py backfill --days 25

# 4. Run full Phase 1 pipeline (Ingestion + Distillation to dense substrate + Top 200 checkpoint)
python reality_engine/cli.py run-phase1 --days 25 --top 200 --workers 8

# 5. Audit Top 200 data completeness checkpoint (DELIVERED facts + dense substrate)
python reality_engine/cli.py verify-checkpoint
```

### C. Visual Dashboard Workflow
Launch the interactive Streamlit dashboard:
```bash
python reality_engine/cli.py dashboard --port 8501 --host localhost
# Web interface available at http://localhost:8501
```

### D. All-Peers Ensemble Screening & Alpha Generation
```bash
# Screen top 20 candidates via ALL-PEERS weighted ensemble (FF5 + quality/policy/supply lenses)
python reality_engine/cli.py screen --universe nifty200 --top 20 --ensemble

# Scan for panic/crisis bargain candidates (drawdown absorption)
python reality_engine/cli.py screen --crisis
python reality_engine/cli.py monitor-panic

# Synthesize daily high-conviction multi-lens thesis and export JSON/MD/HTML reports
python reality_engine/cli.py run-daily-alpha --universe nifty200 --top 20 --top-theses 5 --ensemble

# Inspect full intelligence dossier for a single stock (dense substrate + rankings)
python reality_engine/cli.py inspect-stock HAL
```

### E. Transient Event-Graph & Causal Reasoning
```bash
# Trace downstream transmission walk from a macro/policy node
python reality_engine/cli.py trace-causal-chain --node UNION_BUDGET_2026_RAIL_CAPEX --max-hops 3

# Simulate shock propagation across sectors and companies
python reality_engine/cli.py simulate-macro-shock --shock COMMODITY_CRUDE_OIL --sector ALL

# Spawn a transient event-graph (e.g. US tariff removal): parse %/date/exceptions, 2nd-order fwd/back supply chain
python reality_engine/cli.py spawn-event-graph --event US_TARIFF_TEXTILE_RELIEF --max-hops 3

# Inspect per-stock/sector/geo + investor-majority model rankings
python reality_engine/cli.py rank-models --symbol HAL --investor-majority FII
```

### F. Continuous Self-Correction (EOD + Event)
```bash
# EOD correction batch: EOD price + FII/DII + major event → re-rank lenses, mutate embeddings, update substrate
python reality_engine/cli.py correct-eod --universe nifty200

# Event-driven correction (material news only, NOT intraday noise)
python reality_engine/cli.py correct-event --event US_TARIFF_TEXTILE_RELIEF

# Show learned per-scrip noise floors
python reality_engine/cli.py noise-floor --symbol TITAGARH
```

### G. Inbox Ingestion & Concall Search
```bash
# Process research reports and charts from reality_engine/data/inbox/
python reality_engine/cli.py process-inbox

# Macro feeds: central and state budgets, PIB, RBI (fetch-headless is an alias of fetch-macro)
python reality_engine/cli.py fetch-macro --source pib

# Search concall transcripts and investor presentations (hybrid lexical + vector)
python reality_engine/cli.py search-concall --query "order book capex margin guidance" --symbol TITAGARH
```

### H. Substrate Trust & Analog Peers
```bash
# Materialize the quarantine key set and print the degradation report
# (test fixtures, demo seeds, synthetic-ISIN companies; constant features, etc.)
python -m reality_engine.scripts.run_substrate_hygiene

# Precompute analog nearest neighbours over the dense substrate (structural families)
python -m reality_engine.scripts.run_peer_graph --top-k 20
python -m reality_engine.scripts.run_peer_graph --dry-run    # gate report only, no writes
```
Both scripts print an `ALL CHECKS PASSED` block and are idempotent. Read peers back with
`peer_graph.neighbours(conn, "TITAGARH")` — every row carries similarity, coverage, shared
families, the anchor's baseline (so `lift` is interpretable) and the features that drove the match.

### I. Pilot extraction: write contracts, whole-page recall (T-016), page OCR (T-034) and the number check (T-040)

The pilot-60 extraction stores 16 measure tables (`reality_engine.pilot.extract60.TABLES`).
Code: `reality_engine/contracts.py` (the contracts), `reality_engine/pilot/extract60.py` (selection,
prompts, the single write path), `reality_engine/pilot/proto3.py` (the dry run and the T-040
re-read), `reality_engine/tests/test_contracts.py` (acceptance checks).
Each measure now has a typed contract in `reality_engine/contracts.py`: allowed unit, numeric
range, and the words its own quote must print within 60 characters of the number. The number
must be in the quote; a digit that only appears inside a label (`Q4` read as 4.0) is rejected.
Evidence is typed: a document page (`page >= 1`), an XBRL filing (`source == "results_xbrl"`,
whose quote prints rupees and is compared at /1e7), or a BSE announcement headline
(`source_doc_id` starts with `bse_ann:`; announcement tables may carry a headline instead of a
page). Every row still needs `known_at` and its period.

`extract60._write` is the only INSERT path for the measure tables (Arm A code rows, the
announcement regex pass, the BSE rating feed, the model reader and `repair` all go through it):
it runs `contracts.check` first, and a rejected row goes to `extract_reject` with the reason
`contract:<measure>:<code>` (counted per measure) — never dropped silently. `proto3.py` has no
direct measure-table INSERT.

Recall: a number-dense chunk is sent to the reader whole instead of through the passage picker.
Measured on the 3-company store (2026-11-02): 4,265 chunks, density p50 9.2, p75 22.4, p90 39.2
numbers per 100 words; the rule is `>= DENSE_MIN_NUMBERS (20)` numbers and
`>= DENSE_PER_100_WORDS (30.0)` per 100 words, which marks 622 chunks. A whole page is never cut;
a prompt splits only at `READER_INPUT_LIMIT_TOKENS (100,000)`. A dry run with no model calls
prices it at 3,356,735 input tokens / $0.5035 for the three companies (dense pages alone:
3,053,429 tokens / $0.458); the previous passage-picker Arm B run used 667,305 input tokens.

```bash
# New contract tests (16 passed)
python -m pytest reality_engine/tests/test_contracts.py -q
# Existing module tests (30 passed, 6 skipped: artifact/report tests need a built DB)
python -m pytest reality_engine/tests/test_extraction_pilot60.py -q
# Read-only dry run: stored rows vs contracts + whole-page token/cost estimate (no model call)
python -m reality_engine.pilot.proto3 dryrun
```

`dryrun` reads `extract_proto3.db` from the worktree when present, else from
`REALITY_DATA_ROOT`, and writes only `.tmp/proto3/dryrun.json`. Its 2026-11-02 read:
1,042 rows kept and 158 rejected (13.2%); the top tables are `capex_project` 1/4,
`company_price_revision` 2/6, `company_segment_pnl` 25/72 and `rating_action` 7/16, and no
table is over 90%. The biggest reject class is `measure_term_absent`: a chart-axis or table-cell
quote prints the number but not the word that says what it is.

`REALITY_EXTRACT_TIMEOUT` sets seconds per reader call in `reality_engine/pilot/extract60.py` (default 300). At the old 90 seconds, every max-effort call timed out (121 to 164 s measured on 2 Nov) and counted as an empty document, and one max-effort call spent all 32,000 output tokens and returned no text, so the reader runs at `~low`. Progress lines now show errors.

#### Page OCR overlay for thin deck pages (T-034)

The HP job writes one row per page to `tasks/pilot60/proto3_text/ocr_pages.jsonl.gz`
(`isin`, `symbol`, `doc_type`, `doc_date`, `file_name`, `sha256`, `page`, `text`,
`mean_confidence`, `low_conf_numbers`, plus `why`, `existing_chars` and `existing_text`
from `tasks/pilot60/proto3_text/thin_pages.py`). The file is optional at run time:
`extract60.load_store` joins its rows to `doc` by `sha256`, and a missing file changes
nothing. `REALITY_OCR_OVERLAY` overrides the path; an empty value disables the overlay.

- `why="thin"` means that PDF page has under 400 characters of text layer (measured on the
  three companies' 2,107 deck pages, 2026-11-02: every one of the 352 pages under 200
  characters sits inside a multi-page chunk, so thinness is a page property, not a chunk
  length). Such a row is applied as a one-page chunk `ocr:{doc_id}:{page}` with
  `section="ocr"`, `text_source="ocr"`, the real page and `doc_id`, and
  `low_conf_numbers` — unless its OCR text is blank or its row carries an `error` (T-040:
  a failed page is no reading, and the number check marks its rows `unchecked`).
  An existing chunk's body is never replaced or edited, single-page or multi-page.
- `why="layer_check"` never changes what extraction reads; the numbers in the row's
  `existing_text` and in its OCR text are compared in both directions and logged per
  document in `OCR_STATS["per_doc"][doc_id]["numbers_only_in_text"]` /
  `["numbers_only_in_ocr"]`. Reading `existing_text` from the row means the check works
  for pages inside multi-page chunks too. An errored row is not compared at all.
- A row without a valid `why` is counted in `OCR_STATS["pages"]["bad_rows"]` and not
  applied; a thin row whose `sha256` matches no document is counted in
  `["thin_unmatched"]`. `THIN_PAGE_CHARS` / `REALITY_OCR_THIN_CHARS` are gone —
  `thin_pages.py` decides thinness. `load_ocr_pages` keeps every row, including a blank
  text and an `error` row (they used to vanish, which made the number check report a
  missing page as if it had never been read); `apply_ocr_overlay` is what skips them.
- Every chunk carries `text_source` (`chunk` or `ocr`). The selector sends every whole
  page whole in page order, so an added OCR chunk reaches the reader even with empty
  `tags` and `section="ocr"`. T-040 rule: an OCR chunk is whole only when its text holds
  at least 2 distinct numbers (section dividers print 0 or 1 — 210 of the first 572 thin
  pages — and take the ordinary keyword path); a `chunks_v3` chunk stays whole on the
  number-density rule. `validate` sets `source = 'ocr'` when the matched passage is the
  OCR chunk, and keeps `chunks_v3` when the quote is found only in the original chunk
  (including a multi-page chunk covering the same page).
- `build` prints the overlay summary and stores `OCR_STATS` in `extract_run.notes`;
  `proto3 dryrun` reports the same figures in `ocr_overlay` per company and doc type —
  thin rows applied and unmatched, layer-check pages compared, numbers only in the text
  layer, numbers only in OCR, bad rows, and the input-token change — in
  `.tmp/proto3/dryrun.json` and on stdout.

```bash
# Page OCR overlay fixtures: thin page inside a two-page chunk, reader selection and
# page order, OCR and chunks_v3 quote sources, layer-check numbers both ways, a row
# without why, a missing file, a thin row unmatched to a document, and the T-040
# whole-page rule (1 distinct number is not whole, 2 are) (10 passed)
python -m pytest reality_engine/tests/test_ocr_overlay.py -q
```

#### Number check: confirmed, disputed or unchecked (T-040)

Shivam's ruling (2 Nov): neither the PDF text layer nor the OCR reading is trusted alone,
so every written number carries the verdict of both. T-034 only compared numbers on
`layer_check` pages and logged the differences; T-040 compares each extracted number's
own printed token at write time and records it in a table. Known text-layer faults it
must catch: a Tata Elxsi page prints `0055.19` where the PDF shows `10,056.19` (the
digits are a broken glyph run, not a value), and another page's font encoding yields
`D00349` (not a number at all, so it is absent from both number sets).

- Table `number_check` in the extract DB (DDL in `extract60.py`; additive, none of the
  16 measure tables gains a column): `table_name`, `row_pk` (the measure row's primary
  key as text — all 16 tables are `WITHOUT ROWID`, so there is no rowid), `doc_id`,
  `page`, `printed_token`, `in_text_layer`, `in_ocr`, `quote_source`,
  `ocr_mean_confidence`, `in_low_conf`, `other_token`, `status`, `reason`,
  `resolved_value`, `resolved_by`.
- The token is the one the row's own value came from, found in the row's quote through
  the validator's matcher (`printed_tokens`, shared with `numbers_in`/`value_in`, so the
  same regex and the same 2% tolerance apply). It is compared, normalised with
  `_page_numbers` (`1,000` and `1000` are one reading), against that page's
  `existing_text` (text layer) and `text` (OCR). `confirmed` when both carry it;
  `disputed` when only one or neither does, including a blank OCR text with no error;
  `unchecked` with a `reason` of `no_value`, `no_page`, `no_ocr_row`, `ocr_error` or
  `no_printed_token`. `other_token` is the other source's reading of the same number —
  a similarity pick, not a binding: it can only become `resolved_value` if a re-read
  equals it exactly.
- `_write` is still the only path that stores a measure row: after `contracts.check`
  accepts it, the same call records the verdict. Rows already stored are not rewritten
  (`INSERT OR IGNORE` → `rowcount == 0`), so re-running `build` keeps a resolution.
  `repair` deletes and re-inserts the measured rows and therefore recomputes the
  verdicts: run `recheck` again afterwards. No measure row is ever edited by the check.
- `python -m reality_engine.pilot.proto3 recheck` re-reads each `disputed` row with the
  existing RapidOCR engine on the MSI CPU (no model call, no network, no GPU): it renders
  the PDF page from the doc's `raw_path`, locates `printed_token` with PyMuPDF
  `search_for`, crops it with a 12 pt margin at 600 DPI and OCRs the crop; a token it
  cannot locate falls back to the whole page at 400 DPI. The row resolves only when the
  re-read equals exactly one of the two candidates (then `resolved_value` and
  `resolved_by='rapidocr_crop'`); otherwise it stays `disputed`. It prints counts by
  status and by which source won (the quote's own reading or the other one) and writes
  `.tmp/proto3/recheck.json`. It edits only a copy under `.tmp` —
  `REALITY_RECHECK_DB`, or a `REALITY_EXTRACT_DB` that points under `.tmp`, else
  `.tmp/pilot60/extract_pilot60.db` — and refuses the live store.
- `proto3 dryrun` gains a `number_check` block: counts by status per company and doc
  type (joined to the doc by `doc_id`), totals, and the `unchecked` rows split by
  `reason`. `{"present": false}` when the DB predates the table.

```bash
# Number-check fixtures: both readings confirmed; 10,056.19 vs 0055.19 disputed from
# either quote source; 1,000 == 1000; no row and an errored row unchecked; blank OCR
# disputed; write path stores the verdict and leaves the measure row alone; the dry-run
# block's counts; recheck resolves on an exact candidate and stays disputed otherwise
# (15 passed, engine stubbed)
python -m pytest reality_engine/tests/test_number_check.py -q
# The four pilot acceptance files together (71 passed, 6 skipped: artifact tests need a built DB)
python -m pytest reality_engine/tests/test_number_check.py reality_engine/tests/test_ocr_overlay.py \
    reality_engine/tests/test_contracts.py reality_engine/tests/test_extraction_pilot60.py -q
# Disputed numbers re-read on an enlarged crop (free CPU OCR; needs the DB under .tmp)
python -m reality_engine.pilot.proto3 recheck
```

### J. Query layer v4: the extract-row load and passage answers (T-038)

`extract_proto3.db` was built before the contracts, so the v4 loader re-checks every row and
routes it with a declared measure map (`reality_engine/query/v4/load_fact.py`):

```bash
# load into a COPY of fact_v4_pilot.db (never the live store); prints loaded / existing /
# contract-failing / unmapped counts
python -m reality_engine.query.v4.load_fact --fact .tmp/proto3/v4/fact_v4_pilot.db
```

Its 2026-11-02 read of the three-company extract store: **218 rows loaded**, 3 already present,
**108 refused by `contracts.check`** (the store's two `nim_pct` rows are both above 25% and stay
out) and **844 rows over 375 measures with no mapping, listed and not loaded** — gross NPA is not
loaded as the net-NPA atom. A loaded row keeps `known_at` (the executor cuts `known_at <= as_of`
at read time) and its `doc_id`, `page` and `quote` in the additive `fact_provenance` table.

A narrative question whose decomposer part names no topic or page is answered with
`answer_type = passages`: local BM25 over that one company's chunk bodies, no embeddings, no
model, no paid call, each quote a contiguous substring of the chunk `body`. A passage never
counts as an answer (`case_answered` stays no) and a miss is a typed refusal. The chunk store is
`REALITY_CHUNKS_V3` (`run.Stores.chunks`); a blank `as_of` is `2026-10-19`.

```bash
# KEC's 10 concall PDFs into a chunks store (idempotent on sha256; the raw dir is read-only)
python tasks/pilot60/proto3_text/kec_load.py --db .tmp/proto3/chunks_v3_pilot.db
# the 153 three-company bank rows against stores under .tmp: no model call, no score
$env:REALITY_V4_PILOT=".tmp/proto3/v4"; $env:REALITY_CHUNKS_V3=".tmp/proto3/chunks_v3_pilot.db"
python tasks/pilot60/run_proto3_bank.py
```

The 2026-11-02 run: 153 rows — **35 answered, 11 `passages`, 107 refused**; the top refusal is
142 parts with no row in the store. It also prints how many distinct questions each passage
serves (26 passages: 23 serve one question, 3 serve two — maximum two, against the previous
prototype's two rows for eight questions). Check: `reality_engine/tests/test_proto3_wiring.py`
(10 tests).

A disputed number (T-040) is not loaded unless `proto3 recheck` settled on the number the row stored; the load prints how many it kept out.

### K. Worker review log: calls, tokens, time and Claude's review (T-043)

`reality_engine/scripts/worker_review.py` measures every dsh job and every Claude session
from records only — no model call, no network, and nothing written outside `--out`, so it
is safe to rerun:

```bash
# Workers, Claude, Reviews and Trends sheets; the workbook is generated, never committed
python -m reality_engine.scripts.worker_review build --out tasks/efficiency/WORKER_REVIEW_LOG.xlsx
# The last 5 reviews' prompt / permission / scope changes, for writing the next brief
python -m reality_engine.scripts.worker_review last --n 5
```

The **Workers** sheet takes one row per `plugins/dsh-worker/runtime/jobs/*/` from
`result.md.events.jsonl`, `progress.jsonl`, `status.json`, `job.json` and `brief.md`: tool
calls measured from the event stream (and before the first edit, shown beside the status
record's own count), the brief's `Budget:` total and before-first-edit budget with the
over-budget flags, the worker's own reported total and its gap against the measured count,
the tool mix, failed results and repeated reads, the last progress row's input / cache-read
/ output tokens and model steps, and the commit's changed files and added/removed lines.
When no record reports reasoning tokens, the estimate is `thinking_chars / 4` in
`thinking_tokens_est` (so the column name says estimate) and
`output_tokens_excl_thinking_est` splits it out. `job_type` is filled from a review row
only and stays blank otherwise.

The **Claude** sheet walks `~/.claude/projects/` and `~/.claude-neo/projects/` (the same
junction, read once) for this repo's project directories, reusing
`tool_usage_report.read_claude` so usage is counted once per message id; it adds the tool
mix, the account from a launcher title such as `neo-Info_Diffusion_Model`, and Claude's own
code edits. The **Reviews** sheet shows `tasks/efficiency/worker_reviews.jsonl` as written,
joined by id (a session review id `session-<uuid>` matches the transcript's bare uuid), and
says `review due` where a job or session has no review. **Trends** gives medians of calls,
calls before the first edit, output tokens, minutes, tokens per changed line and the share
over budget, by day and by job type.

First build (2026-11-02): 283 jobs, 37 Claude session transcripts, 6 reviews; job
`20261101T210210Z-521b20a9` measured 164 tool calls, 30 before its first edit (both sources
agree), budget 90 and 20, 99,063 output tokens and 101 model steps. Test file:
`reality_engine/tests/test_worker_review.py` (8 tests).

### L. Watching jobs at every prompt: running, stalled, failed, unreviewed (T-044, T-050, T-053)

`list_workers` returns **running jobs first, then the rest newest started**,
across hosts and with or without a workspace filter
(`plugins/dsh-worker/server/core.py`, `Manager.list_workers`; the MCP tool text
in `plugins/dsh-worker/server/plugin_server.py` states the same order). The old order was
the job-folder name, and because HP folders start with `hp-` they sorted ahead
of every local folder, so a live overnight job could sit past the limit while
25-Oct names filled the page.

`reality_engine/scripts/job_watch.py` prints only the jobs that need attention,
with no model call and no network call. A `UserPromptSubmit` hook in
`.claude/settings.json` runs it on every prompt, so its lines reach the session:

```bash
python -m reality_engine.scripts.job_watch status   # at most 12 lines; silent when healthy
python -m reality_engine.scripts.job_watch add backfill .tmp/backfill.log --pid 1234
python -m reality_engine.scripts.job_watch add ocr .tmp/ocr.log --stall-seconds 900   # slow-commit log: its own quiet window
python -m reality_engine.scripts.job_watch wait     # background it: the harness wakes Claude when it exits
python -m reality_engine.scripts.job_watch ack <job_id_or_name> --note "checked the diff"
python -m reality_engine.scripts.job_watch ack --all-ended
```

`status` reads `plugins/dsh-worker/runtime/jobs/*/status.json`, each active job's `heartbeat.json`
and `result.md.events.jsonl`, `tasks/efficiency/worker_reviews.jsonl` and
`.tmp/job_watch_acks.jsonl`, and only job folders whose
`status.json` changed in the last 48 hours. Lines are `RUNNING <job> <minutes>m,
<tool calls> tool calls`, the count taken from the events file as `worker_status` counts it (T-096;
`progress.jsonl` is a 20-minute digest and only the fallback, for HP jobs and fixtures);
`WAITING <job> for a reply <minutes>m, <tool calls> tool calls, wait ends in <minutes>m` at once when
the worker's turn ended and a follow-up wait is open (`awaiting_input` with a valid
`awaiting_deadline`, the rule of `core._awaiting_input_valid`: a flag with a missing, lapsed or
implausible deadline falls through to the stall rule; a `heartbeat.json` caught mid-write falls back
to the `heartbeat_live` copy in `status.json`); `STALLED` when a running job has been idle more than
10 minutes, idle counted from the latest of `worker_activity_at`, the heartbeat's
`last_activity_at` and a write to `steering.jsonl`, so a reply restarts the window instead of
reading as a stall before the worker's first event (a status ping or a claim restarts it too);
`ACKED <job> waiting for a reply|stalled <minutes>m, <tool calls> tool calls` when that state has
been acked (below); `ENDED BADLY ...` for failed, lost, cancelled or
lease-expired jobs with no review row; and `FINISHED, NEEDS REVIEW <job> <branch>` when a job
finished in the last 48 hours, has no review row (`id`) and is not done yet: merged branches and
merge subjects count as done (three local `git` calls, skipped when nothing needs it), and so does
a branch that no longer exists (deleted after review; an empty branch list means `git` did not
answer and proves nothing). STALLED and WAITING, then RUNNING and ACKED, come first whatever their age; the rest sort
newest first, so the 12-line cap drops the oldest history and never a live job. A registered
non-worker process is `STALLED` when its log has not changed for its own quiet window: the
`--stall-seconds S` given to `add`, else `JOB_WATCH_REGISTERED_STALL_SECONDS`, else 5 minutes (an
OCR run commits every ~20 pages, so a slow one registers a longer window and stops raising false
stalls that block the Stop hook), and `ENDED` when its `--pid` is gone; a
registration without a pid keeps `wait` watching while its log is still changing, then stalls. Its
record is `.tmp/job_watch.json`. Exit code is 0 in every case and a corrupt record is skipped.

`wait [--timeout-seconds N] [--poll-seconds 20] [--ignore-existing]` first reports anything already
waiting for review: before it takes its baseline it returns the existing `STALLED`, `WAITING`, `ENDED`,
`ENDED BADLY` and `FINISHED, NEEDS REVIEW` lines, so a finish that landed while the session was
busy is never swallowed (`--ignore-existing` restores the old behaviour of hiding those lines in
the baseline). It then polls and exits 0 as soon as a line moves to STALLED, WAITING, ENDED or FINISHED
that was not in that state in the baseline (a state that passes leaves the baseline, so a second
stall or wait of the same job fires), or as soon as no job record is active and no live
registered process remains (the records are read again, not the 12 capped lines, and the poll
snapshot is uncapped, so a finish ranked past the cap cannot hide). An invalid or half-written
`status.json` counts as active, so a poll landing between two writes neither crashes `wait` nor
lets it exit with nothing to say. On the timeout (default 3300 s) it prints
`TIMEOUT still running: <lines>`, joined by ` | `. While it runs it keeps one file per waiter,
`.tmp/job_watch_wait/<pid>.json`, holding its pid, process creation time and start time, and
removes that file on every exit, Ctrl-C and exception included (try/finally); two waiters cannot
remove each other's record, and a hard-killed waiter's file reads dead because the pid is gone or
its creation time no longer matches (Windows: psutil when installed, else ctypes
`GetProcessTimes`; pid-only when the OS will not say). Run it as a background Bash command: Claude
is woken when the command exits, which is what makes a finished worker reach it without a prompt.

`ack <job_id_or_name> [--note TEXT]` appends `{"id", "acked_at", "note"}` to
`.tmp/job_watch_acks.jsonl` and removes a registered name from `.tmp/job_watch.json`. An ack covers
only a state that began before `acked_at` (T-096). An acked stall or reply wait reads `ACKED`, which
is outside the `wait` states, passes the Stop hook and asks for no armed waiter; once the worker acts
again, its next stall, wait, failure or finish is raised afresh, so acking a live worker cannot hide
how it ends. `worker_reviews.jsonl` rows have no date and hide a job's end state as before; they do
not touch a live job's line. `ack --all-ended` acks every `ENDED` and
`ENDED BADLY` line shown; `STALLED`, `WAITING` and `FINISHED, NEEDS REVIEW` are left for a real look.
The Stop hook (`reality_engine/scripts/session_hooks.py`) blocks one stop on `WAITING` as it does on `STALLED`.

Fixture and worktree overrides: `JOB_WATCH_REPO_ROOT` (defaults to this checkout),
`JOB_WATCH_ACKS`, `JOB_WATCH_STATE`, `JOB_WATCH_WAIT_DIR`, `JOB_WATCH_REGISTERED_STALL_SECONDS`
(default 300, the registered log-quiet window when the record has no `--stall-seconds`) and the
existing `DSH_WORKER_RUNTIME_DIR`.

First measured `status` run (2026-11-02, 284 job folders): 0.36 s wall (0.29 s in process), one
running job and eleven failed/needs-review lines. Tests: `python -m pytest
reality_engine/tests/test_job_watch.py -q` (51 tests) and the real-subprocess stress suite
`reality_engine/tests/test_job_watch_stress.py` (14 scenarios: a worker that starts waiting wakes `wait`
within two polls, an ack stops `wait` and the Stop hook until the worker waits again, finish before the baseline,
running to finished within two polls, corrupt status during a poll, 40 jobs, a finish past the
12-line cap, a registered job stalled without a pid and a registered pid that exits, a
hard-killed waiter plus pid reuse, two waiters, Stop-hook latency over 40 jobs (measured 0.4–2.0 s
across seven runs on the MSI; the suite fails above 3 s), timeout line).

### L3. Opus headless analysis sessions (T-160, 10 Nov 2026)

`python tasks/night_loop/opus_headless.py start <name> <brief.md> [--hours 3]` runs `claude -p` with Opus 5.5 (effort
high) on the Wolf account (`CLAUDE_CONFIG_DIR=C:\Users\warri\.claude-neo`), hidden and detached through
`Win32_Process.Create`, with only the reality-data MCP, no Edit/Agent/commit/merge/push tools and a 600k context stop.
It is for reading and judgement work DeepSeek cannot do alone (audits of held-but-not-queryable data, independent
grading of a worker's sample); it changes no code and writes only the files its brief names. Status, transcript, log
and the final answer go to `D:/RealityEngine/night_loop/opus/<name>/`; briefs live in
`D:/RealityEngine/night_loop/opus/briefs/`. `status <name>` prints the status file. Shivam allowed spare Wolf usage
for this on 10 Nov.

### L2. One provider session per dsh worker (T-069)

Every dsh worker sends its own `x-opencode-session`, stable for that worker's whole run, follow-ups and restarts
included, and different from every other worker's. `reality_engine/scripts/go_session.py`
`worker_session_id(job_id, model, key)` puts the job id in the uuid5 `job` part; the plugin
(`plugins/dsh-worker/server/core.py`, `_provider_session`) reports that value in `job.json`/`status.json`, and the
harness (`reality_engine/scripts/run_deepseek_harness.py`, `build_patch` and the status metadata) sends the same
value as the header, so both are computed by one shared function. The plugin passes the job id as `--job-id`; a run
started by hand derives it from the resolved `--out-file` path, so repeating a command repeats its id and a different
out-file gets a different one. HP jobs (`reality_engine/scripts/hp_worker.py`) do not call `go_session` directly;
their out-file is `jobs\<job_id>\result.md`, so the harness fallback gives each HP job its own stable id.
`session_id(job, model, key, lane)` keeps its signature for every other caller. Tests, one file per process and no
model run: `python -m pytest reality_engine/tests/test_dsh_worker_plugin.py -q` and
`python -m pytest reality_engine/tests/test_deepseek_harness_controls.py -q`.

### M. Doc review loop and session hooks (T-045)

`reality_engine/scripts/doc_review_loop.py` reviews docs with fresh Haiku 5.5 sessions (`claude -p`, medium effort, tools Read, Grep, Glob and Edit only). The queue is `git ls-files` minus `tasks/handoff/DOC_REVIEW_PROGRESS.csv`, smallest first, so a killed run resumes. It refuses to run on `main`.

- **Size:** a batch is at most 90,000 characters and 12 files; a larger file is split across sessions. A session whose context reaches 95,000 tokens is killed and retried at half the size.
- **Guards, in code:** edits outside the batch, new files, deletions and a net cut above 40% of a file are reverted. Rulings, the bank and its source files, the archive and the tracker are never sent; `tasks/ar_study/text/` is recorded as generated, unread (the folder itself was deleted 3 Nov 2026).
- **Stops:** usage limit sleeps 15 minutes; 3 failures in a row, or $25 estimated at list price, stops it. The log's last line starts `DONE`, `STOPPED` or `PAUSED`. The estimate leaves out sessions killed at the context limit, which report no cost.
- **Overnight:** `reality_engine/scripts/doc_review_keeper.py` restarts the loop 20 minutes after a failure or crash, at most 12 times, with no model call. Done, the budget stop and a file too large for a batch end it, with a `KEEPER ended` line in the log. Each restart counts its $25 afresh.
- **Blind spot:** the reader sees a worktree with no gitignored files and cannot read the archive, `.tmp` or the dsh runtime folder. The first run wrote false "not in the repo" notes from this, so the prompt now forbids that claim; check any such note against the main checkout before merging.
- **Archive:** `--archive` reviews only `tasks/archive/`, with Read, Grep and Glob and no Edit: archived records are history, so each file is kept or proposed for deletion. Shivam lifted the archive read rule for T-045 on 2 Nov; the loop drops it from the worktree's `.claude/settings.json` only (hidden from git with skip-worktree) and puts it back when the run ends. The rule stays on `main`. First run, 2 Nov: 78 files in 9 sessions, 56 kept, 22 finished briefs deleted after Opus checked that nothing outside the archive names them.

`reality_engine/scripts/session_hooks.py` holds two hooks. `stop` blocks one stop while `job_watch` reports a stalled job, while an unreviewed `FINISHED, NEEDS REVIEW` or `ENDED BADLY` line is shown, or while a job runs with no live `job_watch wait` recorded in `.tmp/job_watch_wait/<pid>.json` (section L); it reads the uncapped line list (so a review ranked below the 12-line prompt cap still blocks), never blocks twice in a row, never inside the loop, and never waits itself. `precompact` prints what a summary must keep. Tests: `python -m pytest reality_engine/tests/test_doc_review_loop.py reality_engine/tests/test_session_hooks.py -q`.

The stream/context runner is shared with the T-048 gap loop: `reality_engine/scripts/session_runner.py` owns `child_env`, `context_of`, `build_cmd`, `run_session` (process, stream-json parse, usage, tool calls, the 95,000-token kill) and `estimate_cost` (a killed session's cost from its tokens at Haiku 5.5 list price when no `result` event arrived); `doc_review_loop.run_batch` keeps only the doc queue and its prompt. Its tests still pass unchanged.

### N. One-company gap loop (T-048)

`reality_engine/gap_loop/` answers one company's question bank in rounds, finds why each answer failed, fills the gap by extraction from the company's own documents or by a formula on stored numbers, and answers again. KEC is the first company; `--company BAJFINANCE` and `--company HINDALCO` run the same loop on those two (T-048, 2 Nov; `--company` defaults to KEC). Cheap models do the work and it escalates only on repeated failure. `reality_engine/gap_loop/__main__.py` is the `python -m` entry and calls `loop.main`. Sessions start through `reality_engine/scripts/session_runner.py` in a new console that is hidden (`hidden_console`), so the Bash and Python calls they make open no windows on this laptop; start the loop itself hidden too (`Win32_Process.Create` with `ShowWindow=0`, or `pythonw`). Each live session also keeps `C:\Users\warri\.claude\headless-sessions\<pid>.json` (model, label, a one-line description of the work from `tiers.describe`, start, last step, peak context, tool calls and the last Bash command; `Heartbeat` in the runner, removed when the session ends), which the `headless-sessions` Claude Code mod shows above the prompt and as `claude -p: N running` in the status line.

```bash
python -m reality_engine.gap_loop --sandbox D:\RealityEngine\sandbox\kec_loop --dry-run
python -m reality_engine.gap_loop --sandbox D:\RealityEngine\sandbox\kec_loop --prepare-only
python -m reality_engine.gap_loop --sandbox D:\RealityEngine\sandbox\kec_loop
python -m reality_engine.gap_loop --sandbox D:\RealityEngine\sandbox\kec_loop --ledger-summary \
    --opus-transcript <managing session .jsonl> --since <ISO time>
python -m reality_engine.gap_loop --sandbox D:\RealityEngine\sandbox\bajfinance_loop --company BAJFINANCE --prepare-only
python -m reality_engine.gap_loop.keeper --sandbox D:\RealityEngine\sandbox\kec_loop \
    --log D:\RealityEngine\sandbox\kec_loop\logs\loop.log [--wait-pid N]
```

**Companies (`--company`, `reality_engine/gap_loop/company.py`).** `COMPANIES` holds one frozen `Company` per symbol: `symbol`, `name`, `isins` (a tuple), `bse_code`, `db_name`, `questions` (relative to the sandbox) and `raw_sources` (the `D:\RealityEngine\raw` folder the PDFs came from). `main` calls `company.activate(symbol)` once; every module then reads `company.current()` for its ISIN filter, symbol, BSE code, database name, prompt names, the `job_watch` name (`<symbol lower>_gap_loop`), the HP sandbox (`C:\RE\sandbox\<symbol lower>_loop`) and the DeepSeek write scope. An unknown symbol stops the run with `STOPPED unknown company`. The configured companies:

| `--company` | Database | ISINs (all copied) | BSE code | Sandbox |
|---|---|---|---|---|
| KEC (default) | `kec.db` | `INE389H01022` | 532714 | `sandbox\kec_loop` (unchanged) |
| BAJFINANCE | `bajfinance.db` | `INE296A01032`, `INE296A01024` (changed 2025-06-16 at the split) | 500034 | `sandbox\bajfinance_loop` |
| HINDALCO | `hindalco.db` | `INE038A01020` | 500440 | `sandbox\hindalco_loop` |

Every store copy filters with `isin IN (?,...)` over all the company's ISINs (`prepare.store_copies`, `prepare.duck_copies`). The `ann` copy filters on the symbol. KEC's own site-transcript manifest is read for KEC only. Each company's sandbox holds `raw\history\` (copied, not moved, from `D:\RealityEngine\raw\pilot60_history\<SYMBOL>\`, keeping its subfolders), `questions\` (written by Opus, never by the loop or prepare), `state\`, `logs\` and `reports\`. `--prepare-only` needs no question file, so a sandbox can be prepared before its bank exists; every other command needs `questions\<company's questions file>`. The KEC dry run prints the same plan as before this change. The prepare stage reads the read-only stores from `REALITY_DATA_ROOT` (default `reality_engine\data`), so set it to the checkout that holds the stores when running from a worktree. The `KEC_GAP_LOOP` environment variable keeps its name for every company (the session-title hook looks for it); the HP sandbox and the database copy sent there follow the company.

The dry run prints round 1's units, sizes and tiers and calls no model. A real run first executes the prepare stage (code only, no model); `--prepare-only` runs just that stage and prints its counts. Claude starts a real run after review; the loop never edits `questions\` and never writes outside the sandbox (the job_watch state file is the one exception the ticket asks for).

- **Prepare, before round 1** (`prepare.py`, code only, no model, idempotent). Raw `reality-data` replies cannot fit a 100k session, so Python does the bulk work once: every PDF under `raw\` is read page by page with `fitz` into `kec.db` `doc_text` (a page under 50 characters of text is stored `method='needs_ocr'` with empty text, OCR being a fix-stage job), an FTS5 index (`doc_text_fts`, trigger-synced) covers the text, a `docs` row per file carries `doc_key` (path under `raw\`), doc type, title, filing date and `known_at`, and KEC's rows are copied out of the read-only stores the server reads (via `reality_engine.db.readonly.connect_ro`), each copy recorded in `sources` with its source table and key. A held PDF is dated from BSE's `bse_announcements.ann` (file stem = NEWSID, else the attachment name; the sandbox's `history\` names are NEWSIDs, not attachment names), from `corporate_documents` (publication/dissemination dates only: `doc_date` is the crawl date), or from KEC's site `_manifest.json` / `_known_at.json` by sha256. A file that cannot be dated gets `known_at` NULL and cannot back an as-of answer. Every step skips what is done, and the stage appends one `tier=0` `prepare` unit to the ledger with files, pages by method, rows per table and seconds. It stops the run before any answer when more than a third of the PDFs under `raw\history` are undated.
- **Tiers.** Tier 1 is one fresh `claude -p` Haiku 5.5 session per unit (batch of at most 5 questions, `--effort medium`, stream-json, kill at 95,000 context tokens) whose strict MCP config holds no servers at all, so no `reality-data` call can fill the context; it reads `kec.db` only, with small SQL (always `LIMIT`) and FTS queries run through Bash/Python. A unit fails only on a malformed report (no valid JSON, a qid missing, a bad status or gap type, a qid that is neither one of the unit's questions nor in the company's bank) or an over-limit kill; it halves after each over-limit kill (the half left over is queued; the check then expects only the half's questions, `loop.run_unit` passes `u=current` to the accept function) and goes to tier 2 after 2 failed Haiku attempts. The prompt (`tiers.answer_prompt`) caps each command at about 20 rows and 2,000 characters. Answer and re-answer units run 4 sessions at once (`loop.PARALLEL`, threads with their own SQLite connection, WAL mode, 30 s busy timeout); fix units run one at a time so each ledger row's added rows are its own. Round 1 resumes: a restart skips questions that already have an answer row. A computed answer lists only its stated inputs in `numbers` and gives the result and formula in the sentence (`tiers.answer_prompt`); `checks.measure_family` matches whole words, since "operations" once read as a percentage. `checks.check_number` reads a currency prefix glued to digits ("INR993 crores"), plural suffixes ("Crores", "lakhs") and "80%"; a money unit passes a contract that names another money unit. `--hp-slots N` adds N answer sessions on the HP laptop (`reality_engine/gap_loop/remote.py`): before each answer stage a SQLite backup of `kec.db` is copied to `C:\RE\sandbox\kec_loop` with scp, the prompt goes over as a file and is piped into the HP's `claude -p`, and stream-json comes back over ssh; fix units stay on this laptop because they write. The HP CLI signs in from its own `CLAUDE_CODE_OAUTH_TOKEN` user variable, which Shivam set; the loop never handles a key. Every session's full stream-json (each tool call with its whole command and result) is kept in `state\transcripts\<unit>__<model>__<start>.jsonl` (`tiers.transcript_path`, `run_session(transcript=...)`), with the scripts sessions wrote under `state\<unit>\`; the ledger keeps only the first 200 characters of each command. These are the record for mining the query patterns and the schema; `tiers.fix_prompt` makes every script start with `SOURCE:`, `METHOD:` and `FIELDS:` lines so the extraction methods can be catalogued and rerun over all raw records. `--recheck` re-runs the current checks on unverified rows with no model call and stores the ones that now pass as answered (`rechecked: true`). A row citation passes when the value is in the row at a money scale (crore against million, lakh or rupees) or inside a text field such as an announcement headline; an answer's `known_at` comes from the cited page's filing record; `9MFY26` and `H1FY27` are periods. A fix unit's proposals are checked line by line (`loop.accept_fix`): a bad line is counted as rejected and the rest are stored. A proposal with `table` and `rowid` is checked by `checks.check_row_fact` against that row and stored in `row_facts` (T-048 fix, 2 Nov: Hindalco's row proposals had failed on "page not in doc_text"); one without them is checked against its `doc_key` and `page` and stored in `facts`. `known_at` is taken from the cited row's or page's filing record, never the model. A valid formulas file is stored even when every fact fails, and the unit fails only when nothing at all is stored. `store.add_formula` stores list inputs as JSON text, and `loop.main` writes its `STOPPED` line with the failing source line to the log as well as stderr. Tier 2 is one fresh Sonnet 5.5 session at medium effort (`tiers.run_tier2_sonnet`, same tools and 95k kill; Shivam, 2 Nov). The older DeepSeek tier 2 (`tiers.run_tier2`, the `Manager.start_worker` function behind the dsh-worker MCP, imported from `plugins/dsh-worker/server/core.py`; a peak-hour refusal queues the unit) is kept but is no longer the default. Tier 3 writes one line per question that got no valid row to `escalations.jsonl`, with its last check reason and everything tried, and the loop moves on; the run registers its log with `job_watch add` so the managing Opus session sees it.
- **Dsh workspace limit (DeepSeek tier 2 only).** `start_worker` refuses a workspace outside the repository, so a tier-2 unit starts at the repo root with `write_scope='data'` (danger-full-access), `confirm_repo_root_write=True` and `approved_by="Shivam, 2 Nov: full permissions inside the T-048 sandbox"` so the job record says who approved that write, and a brief that pins every write to the sandbox. The dsh job record carries tool calls but no token counts, so the ledger writes `tokens: null` with a note instead of guessing.
- **Checks, in code, before a row is stored or an answer counted** (`checks.py`): a number cites either a `doc_text` page or a row of the sandbox's `kec.db`. A page: the quote occurs on it; the number occurs in the quote (Indian digit grouping and crore/lakh/million words; a period before a number only disqualifies when a digit precedes it, so `Rs.1,23,456 crore` is read and `1.56` is not split); `known_at` is the page's filing date and not after the as-of date. A row (`table` + `rowid`): the loop reads that row with `store.row_lookup`, and the number, and the quote when one is given, must occur in it (a numeric column counts as its own text, so `7540000000.0` is a quote of that column); the row's own `known_at` must equal the answer's and not be after the as-of date. Both need a measure, a unit that suits it (margin is a percent, order book is money, and `contracts.CONTRACTS` units are reused when a measure is named there) and a stated period. A malformed report fails the unit; a number that fails a check leaves its row stored as `unverified` with that reason, not counted as answered, and the next round fixes or re-answers it. (T-051, 3 Nov: `loop.accept_answers` also reads the company's bank through `loop.bank_questions`; a report row whose qid is neither one of the unit's questions nor a bank question is rejected in the `invalid` map, exactly like a missing row or a bad status, and the loop stores nothing from that report — the T-048 Hindalco run had stored an answer for `HINDALCO029b`, a qid in no bank. A bank qid outside the unit stays a real question: it is checked against its own booked `as_of` and stored. Tests: `test_a_qid_outside_the_unit_and_the_bank_is_rejected_and_never_stored`.) (T-048, 2 Nov, for Hindalco and Bajaj Finance: units are normalised for case, spaces and hyphens, so `INR_crore` is `inr_crore`; USD, lakh and crore money units, `<currency or cents>_per_<quantity>` rates, volume, count and `date` units are known; USD converts only to a USD money unit and is read in its own scale; rate phrases such as cost of funds, credit cost, loan loss to average, yield, NIM, ROA, ROE, GNPA, NNPA, coverage and margin are percentages, `per share` and `face value` are money, and `share` beside a money word has no measure family, so its unit is not fit-tested; periods accept `Dec-2025`, `12-month trailing`, `trailing twelve months` and `LTM`.)
- **Gaps and fixes.** A `not_found`/`partial` answer carries one gap type: `text_missing`, `not_extracted`, `needs_formula`, `wrong_store` or `absent`; `unverified` is assigned by the loop, never reported by a model. Fix units are one group per gap type, at most 10 questions each, so 25 questions of one type are three units (absent is recorded, not fixed). Extraction scripts write page text straight into `doc_text` but only propose facts/formulas under `state\proposals\`; the loop checks and stores them, so a model never writes `facts`, `formulas` or `answers` directly.
- **Rounds.** Round 1 answers all 100 questions; each later round runs the fix units and then re-answers only the questions not `answered` plus the first 10 answered as a regression. At most 5 rounds, and two rounds in a row that close no gap stop it with `DONE`. A round with no re-answerable question also stops it.
- **Sandbox layout** (`D:\RealityEngine\sandbox\kec_loop\`): `questions\` (read-only bank), `raw\` (KEC PDFs), `kec.db` (`doc_text` + `doc_text_fts`, `docs`, `sources`, the copied KEC tables `ar_facts`, `deck_figures`, `results_filings`, `results_quarterly`, `concall_items`, `px_nse`, `px_bse`, `shp_index`, `announcements`, and the loop's own `facts`, `row_facts` (facts cited as a row, not a page), `formulas`, `answers`), `state\` (`ledger.jsonl`, `mcp.json`, proposals, tier-2 unit results, scratch scripts), `logs\loop.log`, `reports\round_N.xlsx`, `escalations.jsonl` (one line per escalated question).
- **Ledger and reports.** Every unit attempt appends one row to `state\ledger.jsonl` and to the `ledger` sheet of that round's `reports\round_N.xlsx`: tier/model, times, attempt and outcome, input/cache-read/cache-creation/output/thinking tokens and cost, tool calls by name, Bash lines cut to 200 characters, method tags the loop proves from the run (`script_text`, `ocr`, `model_read` with read pages, `sql`, `formula`, `labelling`), pages by code against pages read by the model, rows added per table and files written. `cost_usd` is the session's own `result` event `total_cost_usd`; when the session is killed before that event, the cost is estimated from its token counts at Haiku 5.5 list price (`session_runner.estimate_cost`, from the repo's `tasks/kilo_model_pricing_2026-10-12.csv` row: $0.10/M in, $0.50/M out, cache read 0.1x and cache write 1.25x the input price) and the row carries `cost_estimated: true`. `--ledger-summary` totals these per tier and method and gives tokens per question answered; `--opus-transcript` with `--since` adds the managing session's usage blocks so the summary spans all three tiers.
- **Stops and guards.** `$15` estimated Haiku list price per run. A usage-limit reply (`session_runner.LIMIT_PATTERN`, case-insensitive: "hit your 5-hour limit" or "hit your weekly limit", "usage limit", "limit reached", "rate limit", 429, "overloaded", "· resets <time>") sleeps 15 minutes and retries the same tier, on tier 1 and tier 2 alike; it is not an attempt and never escalates (Sonnet tier-2 sessions count toward the same estimate). The 8th such reply in a row in one unit (`loop.MAX_LIMITED_REPLIES`) logs `PAUSED usage limit`, stops the run with exit 5, and a rerun resumes; the unit's rows so far are kept in the ledger. No network fetch and no paid embedding, never `D:\Shivam_Private` or a key file, never a write outside the sandbox. The run refuses to answer when the prepare stage leaves more than a third of the `raw\history` PDFs undated. The keeper restarts the loop 20 minutes after a crash at most 12 times. Log lines end with `DONE`, `STOPPED <reason>` or `PAUSED`. Tests, no model call: `python -m pytest reality_engine/tests/test_gap_loop.py reality_engine/tests/test_doc_review_loop.py -q`.

### O. pilot3 database (T-049)

`reality_engine/pilot3/` builds ONE SQLite database by scripts only (no model, no network), so the pilot questions are answered by plain SQL; it began with KEC, BAJFINANCE and HINDALCO, and since T-056/T-090 the `pilot3_*` tools serve every company the database's `company` table holds. Part A (the core, this section) is `schema.py` (DDL), `registry.py`, `stores.py`, `ratios.py`, `queries.py`, `oracle.py`, `call_dates.py` (transcript call dates, used by `registry.py` and `kpi.py`) and `build.py`; part B (`kpi.py`, `transcripts.py`, `lexicon/`) is a separate worker's; part D is `statements.py` (below). `__init__.py` finds the read-only stores (`REALITY_DATA_ROOT`, else this checkout's `reality_engine/data`, else the main checkout's) and sets `REALITY_DATA_ROOT` before `gap_loop.prepare` is imported.

```bash
python -m reality_engine.pilot3.build --out .tmp/pilot3.db --part all    # registry | ocr | pages | stores | comparatives | preferred | ratios | extract | kpi | transcripts | segments | guidance | notes | checks | all; 484 s on 4 Nov 2026 (23,558 pages) before the ocr part; a first OCR run adds up to --ocr-max-seconds (540)
python -m reality_engine.pilot3.doc_canary --out .tmp/canary --per-cell 3 --seed 0   # unseen companies x doc type x year; a >=20% drop against the previous summary prints
python -m reality_engine.pilot3.oracle --db .tmp/pilot3.db --tables core [--detail]
python -m pytest reality_engine/tests/test_pilot3_core.py -q              # 26 tests; the 2 integration ones build the real db (marked slow, about 8 min)
```

- **Tables** (every fact row carries symbol, isin, period, basis, value, unit, scale, `known_at` from the filing record, and its source: doc + page, or source db + table + rowid/file). `company` (every ISIN a symbol has had: `symbol_isin_history` plus ISINs only other stores use, e.g. shareholding under `INE296A01016` / `IN9038A01010`), `doc`, `doc_page` + FTS5 `doc_page_fts` (copied from the collector's pages.db, the sandbox pages only for documents pages.db lacks; no PDF re-read; a `needs_ocr` page takes the OCR text and its `ocr_conf` from the build's own `<stem>_ocr.db` (`--part ocr`, T-121) or an explicit `build.py --ocr-db`, method `ocr_rapid`), `share_capital` (paid-up / face value per filing, plus split / bonus events and ISIN windows), `fin_quarter_xbrl` (every quarter of `results_xbrl.quarterly`, both bases, 21 XBRL items, long form; revised filings stay as separate rows keyed by `known_at`), `fin_annual_line` (closed caption lexicon over `ar_facts`, `stores.LEXICON`, plus the part D XBRL / deck / annual-report rows below; columns `definition` = reported / xbrl_reported / xbrl_derived / company_stated and `period_type` FY / H1 / Q), `dividend_event`, `price_delivery` (NSE and BSE daily OHLC, delivery, cumulative split factor and adjusted close, from the truth snapshot), `shp_category` (`shp_index` promoter/public per quarter plus holder categories from `D:\RealityEngine\raw\nse_shp_xbrl_pilot` parsed with the stdlib; 2025-05 taxonomy files give fractions, normalised to percent by checking promoter + public ~ 1; `pct_base_shares` / `pct_basis` name the share count the printed percentage is on, T-088), `shp_holder` (the named holders of each quarter from the typed-member contexts of the same files, one row per category and name, a persons-in-concert disclosure in its own `pac_*` category with `pac_name` so it never enters a category sum, the holder's pledged count; T-088), `shp_pledge` (the promoter encumbrance block per quarter: the file's pledge / NDU / other flags, promoter and pledged shares, the printed pledged percentage - of the promoter group's own holding; T-088), `formula` + `ratio_panel` (derived, `is_derived=1`, `formula_id`, `input_refs`, `known_at` = latest input), `valuation_daily` (market cap, trailing EPS restated to the day's share basis by the cumulative split factor, P/E; P/B, EV/EBITDA and dividend yield fill only where `fin_annual_line` has net worth, net debt or dividend per share), and `guidance` (one row per forward-looking numeric target; extractor and rules in O6). **Transcript dates (T-049 review, 4 Nov 2026):** a transcript's `filing_date` and `known_at` are raised to the call date printed in its first pages (`reality_engine/pilot3/call_dates.py`, `known_at = max(filing record, call date)`), because a filing record can date a transcription before the call it transcribes — KEC's Q4 FY26 call, held 18 May 2026, carried the company-site publish date 18 Feb 2026 and answers dated the call from it. `python -m reality_engine.pilot3.call_dates` prints the table (doc_key, stored filing, stored known_at, call date in the text, new dates) for every held transcript and lists the ones no call date was read for: 142 transcripts, 0 unread, 3 filing dates raised (all KEC), 0 known_at raised on 4 Nov 2026.
- **Reads go through the gap loop's copy specs** (`prepare.store_copies`) widened to all ISINs, so the SQL is not duplicated. Rows are read from the real stores, not the sandbox copies, so the one-year window of the sandbox `results_quarterly` is gone (28-31 quarters per company).
- **Definitions.** EBITDA = pre-exceptional PBT + finance cost + depreciation - other income (matches KEC's own 291 crore for Q1 FY27); no EBITDA / EBIT metrics for BAJFINANCE (a lender's finance cost is its cost of goods). FY values are sums of the four filed quarters; FY basic EPS is the sum of quarterly EPS (approximation, noted in `formula`). Company-defined EBITDA (Hindalco FY26 38,097 crore, KEC Q1 FY25 margin 6.5%) differs from the XBRL-derived one and shows as a mismatch, not a failure to fix quietly.
- **Oracle** (`oracle.py`): the newest `status='answered'` row per qid of each sandbox is the reference; `T048_QUESTION_COVERAGE_2026-11-03.xlsx` maps a question to its table; each number of the answer becomes one fixed SQL shape of `queries.py` (`px_on`, `px_extreme`, `fin_quarter`, `fin_annual`, `shp`, `shares`, `ratio`, `valuation`), compared at 0.5% (or half a unit of the oracle's last printed decimal) across crore / million / rupee scales. Numbers whose inputs sit outside part A (AUM, order book, segment EBITDA) are counted apart. First run (3 Nov 2026), questions / reproduced / mismatched / not reachable: ratio_panel 55 / 23 / 1 / 31, price_delivery 21 / 21 / 0 / 0, fin_quarter_xbrl 18 / 14 / 0 / 4, fin_annual_line 25 / 18 / 3 / 4, shp_category 9 / 4 / 0 / 5, valuation_daily 3 / 3 / 0 / 0 (not reachable = a missing table or a question with no check-passing answer).
- **Part D (T-049 D, 3 Nov 2026): the unreachable questions closed by script.** `statements.py` (new) adds, with no model and no network:
  - *XBRL balance sheets, cash flows and annual P&L* into `fin_annual_line` (new columns `definition`, `period_type`): year-end (`FYyy`) and half-year (`H1FYyy`) filings of `results_xbrl.db` (`facts`, contexts `OneI` and year-to-date durations; consolidated and standalone; BAJFINANCE from the NBFC and integrated taxonomies). `definition='xbrl_reported'` = a tag as filed; `'xbrl_derived'` = sum or difference of filed tags: `net_worth` (equity attributable to owners), `total_borrowings` (non-lender: current + non-current; lender: borrowings + debt securities + subordinated + deposits, matches the 4,35,112 crore the call quotes), `net_debt` (borrowings - cash - other bank balances - current investments; not for a lender), `net_debt_all_investments` (the same less non-current investments too, written only when that tag is filed; MARUTI-083: a treasury held in non-current debt funds made plain net debt overstate leverage, so answers give both and say which a ratio uses; `pilot3_ratio(ev_ebitda)` adds `net_debt_all_investments` and `ev_ebitda_all_investments` to each row's inputs and a note when the two differ by more than 10%), `capital_employed` (assets - current liabilities), `capex` (-(PPE + intangibles purchases), cash-flow sign), `trade_receivables`. Values are rupees (`scale` 1); `doc_key` = the XBRL file, `source_rowid` = `file#facts rowid`, `known_at` = dissemination time.
  - *`company_stated`* rows beside the derived ones, never merged: (a) the `stores.LEXICON` now also picks the company's own ratio-note measures from `ar_facts` (net debt including acceptances, total debt including leases, net working capital days, debtor days, ROCE, ROE, net debt / EBITDA) and keeps blank-basis rows as `basis='not_stated'`; (b) `build_company_stated` reads deck / call / press-release / result pages by script: table rows (a label line followed by numeric lines, mapped to the nearest period-token header group only when the column counts agree, `%` columns dropped) and sentences ("EBITDA margins have increased by 70 bps to 6.5%", "net debt, including acceptances is at INR 6,722 crores"); quarter rows have `fiscal_year` `QnFYyy`, `period_type` `Q`. A plausibility gate drops mis-mapped segment rows (EBITDA within 25% of the XBRL-derived one, margin within 3 points, net debt within 40%, leverage 0-15x); the build log prints how many were dropped. Pages come from this database first, then from the collector's `D:\RealityEngine\pilot3\pages.db` (opened read-only, optional); a page used from there is copied into `doc` / `doc_page` so the quote can be checked here.
  - *Annual-report statement pages* (`build_ar_statements`): consolidated / standalone cash-flow and balance-sheet pages of annual reports that `pages.db` holds and this database does not (the Hindalco FY26 report filed 30 Jun 2026: 28 rows; its operating cash flow 10,250 crore equals the XBRL figure).
  - *Dividends*: `dividend_event` (NSE corporate actions, one row per event; final / special by ex-date April-September belongs to the year that closed in March, interim October-March to the year closing next March; `known_at` = broadcast date or the ex-date, which is later than the declaration) and the per-year `dividend_per_share` / `special_dividend_per_share` lines (as declared on the then share basis, so Bajaj FY25 shows 44 + 12 before the split).
  - *Lender quarter fields* in `fin_quarter_xbrl`: `interest_income`, `impairment_financial_instruments`, `fee_commission_income / expense`, `net_interest_income` (= interest earned - finance costs, `is_reported` 0) for BAJFINANCE; the NBFC and integrated taxonomies both use `InterestEarned`, `FinanceCosts`, `ImpairmentOnFinancialInstruments`. Fiscal-year sums of them are in `ratio_panel`.
  - *Balance-sheet ratios* in `ratio_panel` (FY and H1 periods, formulas F_BVPS, F_DE, F_ROE, F_ROA, F_ND_EBITDA, F_ROCE, F_REC_DAYS, F_INV_DAYS, F_PAY_DAYS, F_NWC_DAYS, F_CUR; closing balances over trailing-four-quarter flows, 365-day year; ROCE and ROE use closing capital employed / net worth, not averages). `valuation_daily` now fills P/B, EV/EBITDA from the XBRL-derived net worth and net debt, and dividend yield from the trailing-12-month dividends restated by the split factor.
  - *Lender NIM (T-051, 3 Nov)*: formula `F_NIM` / metric `nim_pct`, lenders only (Bajaj Finance, `ratios.LENDERS`), in `ratio_panel` beside the other balance-sheet ratios: the period's quarterly `net_interest_income` (from `fin_quarter_xbrl`, itself derived as interest earned - finance costs) summed, annualised by x4/n quarters and divided by the average of the balance-sheet `loans` at the period start and end (`fin_annual_line`, `xbrl_reported`; kpi-series AUM is too stale to use — its newest `aum` row is `known_at` 2024-01-29). `is_derived=1`, `formula_id='F_NIM'`, and `input_refs` names every quarter and both loan-sheet rows; `known_at` is the latest input. A NIM the company states itself stays its own `kpi_series.nim_pct` row, never merged into the derived one. `book_value_per_share` (F_BVPS) has FY25 and FY26 rows for all three companies where net worth and a share count exist (Bajaj FY26 183.34 on the post-split share count, FY25 1557.43 pre-split, as filed); `roce` (F_ROCE) has them for KEC and HINDALCO, and is deliberately absent for BAJFINANCE because a lender has no EBIT here (finance cost is its cost of goods).
  - *Shareholding*: the 2025-05 taxonomy files for every quarter to 30 Sep 2026 are already in `D:\RealityEngine\raw\nse_shp_xbrl_pilot` (their header has no `Symbol`, which hid them); the category aliases (`MutualFundsOrUTI`, FPI category one / two) were missing, and `fpi_total` is the pattern's own `InstitutionsForeign` line for those files (Bajaj 30 Jun 2026: mutual funds 9.63%, FII/FPI 20.21%). Nothing needs fetching. T-051 (3 Nov): promoter, mutual-fund and FPI holding by quarter answer in one query for all three companies, e.g. `SELECT quarter_end, category, pct FROM shp_category WHERE symbol='KEC' AND category IN ('promoter','mutual_funds','fpi_total') ORDER BY quarter_end`; `stores.MEMBERS` maps both taxonomy spellings, and `build_shp` keeps every ISIN in `symbol_isin_history`, so older rows sit beside the current ones: BAJFINANCE `INE296A01024` (2024-06-30..2025-03-31) beside `INE296A01032`, HINDALCO `IN9038A01010` beside `INE038A01020`. Coverage: promoter and public 23 / 20 / 22 quarters from 2021-09-30; the SHP-XBRL categories (mutual funds, FPI category one / two, `fpi_total`) 11 / 9 / 11 quarters from 2024-06-30. A quarter can carry two `promoter` rows when the `shp_index` copy and the SHP-XBRL parse are the same filing; `queries.shp` orders the XBRL row first, so an answer reads one value. Test: `test_shp_rows_under_an_older_isin_are_copied_to_the_symbol`. **T-088 (6 Nov 2026):** the named holders are read too (`shp_holder`: `NameOfTheShareholder` and its counts from the typed-member contexts, one row per category and name per quarter, the persons-in-concert twins under `pac_*` with `pac_name` so a category sum cannot count them twice), and `shp_pledge` keeps the file's pledge / NDU / other-encumbrance flags with the promoter rollup's pledged shares and printed percentage - which the corpus proves is of the promoter group's own holding, not of all shares (IDEA 2025-12-31: 11.84% of 27,702,778,543 promoter shares; 3.03% of the total). The printed percentage's base is stored on every `shp_category` row (`pct_base_shares`, `pct_basis`): the total, or the total less the `CustodianOrDRHolder` shares when the issuer has depository receipts (INFY 2026-09-30: 516,677,914 / 3,716,041,606 = 13.90%, not / 4,058,276,578 = 12.73%); of the 591 corpus files 571 print on the total, 11 only on the total-less-custody base, 9 match both and none match neither. The three shareholding tables keep their quarters from `compute_start` (T-088 window rule), so 2025-09-30 and earlier are back. Test: `reality_engine/tests/test_pilot3_shp_holder.py`. **T-162 (10 Nov 2026):** `shp_category.known_at` is the earlier of `shp_index.broadcast_at` and the NSE file name's own submission stamp (`SHP_..._DDMMYYYYhhmmss_WEB`, `stores._shp_known`), because the index time is sometimes a later re-broadcast (ADANIPORTS 2021-09-30 filed 20 Oct 2021, broadcast 7 Jan 2022) and a strict `as_of` dropped quarters already public. The stamp is on a 12-hour clock with no AM/PM, so an hour below 12 is read as PM, and it only wins when even that reading is over an hour before the broadcast (`known_at_source` = `file name timestamp (pm-safe)`). Measured on the live stores: 29 of 198 p20 filings, 25 of 150 u8 and 34 of 202 q12 move earlier, almost all by a day or more; they take effect at the next `--part stores` rebuild. Test: `test_shp_known_at_takes_the_earlier_pm_safe_file_stamp`.
  - *Oracle after part D* (questions / reproduced / mismatched / not reachable): ratio_panel 55 / 39 / 1 / 15 (was 23 / 1 / 31), fin_annual_line 25 / 23 / 2 / 0 (was 18 / 3 / 4), fin_quarter_xbrl 18 / 15 / 1 / 2 (was 14 / 0 / 4), shp_category 9 / 5 / 0 / 4 (was 4 / 0 / 5; the 4 left have no check-passing answer), price_delivery and valuation_daily unchanged at 21 and 3 of 21 and 3. The oracle also looks up `fin_annual_line` quarter rows and `not_stated` bases.
- **Still unreachable, and why.** Hindalco FY26 capital expenditure 31,619 and cash flow from operations 21,858 crore are the company's net-debt bridge chart (its operating inflow before interest and tax, capex incl. advances), whose bars are not in label order on the page; XBRL has 30,096 and 10,250 (kept as `xbrl_derived` / `xbrl_reported`). The 21,858 line is now read by its own sentence ("Healthy Cash flow from operations at ₹21,858 crore") and stored as a `company_stated` `cash_flow_from_operations` row beside the audited 10,250 (both definitions are right and a reader must say which); a bridge-chart rule for the bars would still need an arithmetic check (35,332 - 21,858 + 12,909 + 31,619 + 1,110 + 5,729 = 64,841). Bajaj Q1 FY26 "loan losses and provisions" 1,969 crore is a deck figure; the filed `ImpairmentOnFinancialInstruments` is 2,078 (standalone) / 2,120 (consolidated). 10 ratio_panel numbers (AUM, order book, cost of funds, segment EBITDA) and 6 quarter numbers belong to tables of the other sessions (decks, transcripts). Companies' own EBITDA from decks is read only where the table header and column counts agree; a deck page laid out as a picture (no text) stays unread.

### O2. pilot3 KPI and transcript extractors (T-049)

`reality_engine/pilot3/kpi.py` and `transcripts.py` fill two tables of the T-048 schema with rules only: no model, no AI OCR, no network. Lexicon in `pilot3/lexicon/*.yaml` (`orders`, `lenders`, `metals`, `common` = KPI labels with kind/unit/neg words; `dimensions` = segment words per company; `topics` = transcript topic tags and known management names). Regexes are YAML double-quoted strings, so a backslash is written twice.

```bash
python -m reality_engine.pilot3.kpi --out <db> [--symbols KEC,BAJFINANCE,HINDALCO] [--pages-db D:/RealityEngine/pilot3/pages.db] [--raw-root D:/RealityEngine/raw | '']   # ~6 min for all three with pages.db
python -m reality_engine.pilot3.transcripts --out <db>                                                              # ~10 s; reads the pilot3 db's own doc_page when it has one
python -W ignore .tmp/kpi_oracle.py [--only kpi|sample|tr] [--detail]   # oracle report (needs both dbs in .tmp/)
python -m pytest reality_engine/tests/test_pilot3_kpi.py -q
```

- **Input.** Page text from `pages.db` (`doc` + `doc_page`, every held document of the company; `build.py` passes it as `--pages-db`) and, for the documents pages.db does not hold, from each `<sym>_loop/<sym>.db` (`doc_text` + `docs`, doc types deck, results, press_release, transcript, annual_report, announcement); PDF word positions for table/chart pages from `doc.source_path` (pages.db, else the sha256 copy under `decks_full/`) or `<sym>_loop/raw/<doc_key>` (sandbox), PyMuPDF. `needs_ocr` pages are skipped and counted; with `--ocr-db` (repeatable, one per company) the pages `pilot3.ocr` read are added with `method='ocr_rapid'` and `ocr_conf`. With `--raw-root` (default `D:/RealityEngine/raw`) it also reads the decks that `deck_figures` cites but neither source holds (`decks_full/<sha[:2]>/<sha>.pdf`, text layer only, doc_key `decks_full/...`, known_at from `deck_figures`); switch off with `--raw-root ''`. Read only the sandbox until 3 Nov 2026, the extractor read none of the 52 FY25-FY27 decks and results presentations in pages.db (`deck` 10/9/17 and `results` 7/4/5 for KEC / BAJFINANCE / HINDALCO), which is why Bajaj AUM, new loans, cost of funds and franchise and Hindalco shipments and EBITDA per tonne stopped around FY24. With `--pages-db` every one of them yields rows: KEC 16 of 17 (the 17th is a one-page audio link typed `deck`), BAJFINANCE 13 of 13, HINDALCO 22 of 22, and the FY25-FY27 rows go from 449 / 0 / 0 to 1,183 / 3,580 / 1,731.
- **`kpi_series`** rule ids in `extractor_rule`: `table_v1` (label row + period header row, values paired to header columns by x position; segment from a left-margin heading at or just below the row), `chart_v1` (bare number row over a period axis, titled by a short lexicon label with a unit; skipped when several series share one axis), `sentence_v1` (label ... value [unit] period [vs value period] in running text), `sentence_pair_v1` (period taken from the nearest earlier "A v/s B" header), `sentence_default_v1` (period = document reporting period; for a call or release that states a year-to-date span it is the year-to-date period the span closes on, T-129; lowest confidence, filter it out for strict use), `derived_cumulative_v1` (T-129: a missing flow quarter derived from the cumulative rows, `is_reported=0`, quote names both inputs). Rows: symbol, metric, dimension, value, unit, scale (1e7 crore, 1e6 usd_mn, 1e3 kt), period_type, fiscal_period (Q3FY24, FY24, 9MFY24), as_of_date, basis (consolidated / standalone / not_stated only), entity (the company's symbol or the named subsidiary: 'bhfl', 'bajaj_financial_securities'; T-088), doc_key, page, quote, known_at, raw_label, raw_value, `source_type` (the document type the row came from: deck, results, press_release, transcript, annual_report, announcement, so a reader can filter a call's number away from the deck's), confidence and conf_rank. A call's number keeps its own row at the bottom of the confidence order (`conf_rank` two ranks lower, floor 1: 1,399 transcript rows on 3 Nov 2026), so "INR1,600 crore" from a Q&A never ranks as the deck's order book. Metric names follow the schema; `credit_cost_bps` stores bps only (a % figure is converted x100, noted by raw_value). `usd_bn` is converted to usd_mn, mt to kt, and `MM` (the decks' million) is read as `mn`. A value whose quote is not a literal substring of the page text is never stored. **Period labels:** 31 March closes the Indian fiscal year, so a stock figure dated "as on 31 March 2026" is `FY26` with `as_of_date` 2026-03-31 (an explicit "Q4 FY26" header stays `Q4FY26`); a Q4 document (annual-results deck or call) defaults its unlabelled figures to the fiscal year, and a comparison-period mention ("last year in FY '25") never becomes the document's period. T-129: a call, release or deck whose own text states a year-to-date span ("for the period ended 30 September 2026", "nine months ended", "half-year ended", "H1/9M FYxx", "corresponding period") defaults a figure with no period of its own to the year-to-date period closing on the quarter its first pages name (Q1 -> Q1, Q2 -> H1, Q3 -> 9M); a Q4 document keeps FY, a figure whose own sentence names a period is untouched, and an annual report (or any document over 80 pages) passes `ytd=False`, so its pages keep the page's headline. SBI Life's Q2 FY27 call APE 117.5 bn is H1FY27 and the Q3 FY26 call's APE 185.2 / 168.8 bn and VNB 50.4 bn are 9MFY26. `kpi.derive_quarters` then writes a missing Q2/Q3/Q4 of a flow metric (Q2 = H1 - Q1, Q3 = 9M - H1, Q4 = FY - 9M, per symbol / metric / dimension / basis / unit, best non-quarantined reported input, skipped when that period's rows disagree by more than 1%); only the named flow set `_DERIVABLE_FLOW` is derived, never a stock. Measured on a pilot10 copy: 215 periods moved by the default rule and 47 derived rows written; the independent checker quarantines all 47 derived rows on the synthetic quote (blueprint 9j).
- **Segment mix tables (`mix_v1`, 4 Nov 2026).** A table whose title names the metric ("Business segment wise AUM - Consolidated") and whose rows are segment names is a mix: one row per line with the segment as `dimension`, the Total line as `total`. The value column is the latest period on the page, preferring the column whose entity heading ("Consolidated | BFL | BHFL") is the page's entity (`page_basis`), so the consolidated 31 Mar 2026 column is read and not BFL's or BHFL's. At least three segment lines are required, so a product sub-table (Home Loans / LAP under "AUM - Mortgages") is not mistaken for the mix. Two chart/text rules sit beside it: a donut chart's percentages are paired with its legend in printed order (`chart_v1`) under `<metric>_mix_pct` (`order_book_mix_pct` 63/27/7/2/1 from "Order Book – 31 Mar'26", `order_intake_mix_pct`, `revenue_mix_pct`), the run belonging to the nearest title with no other chart title between them; and a business-wise revenue bullet block ("•Revenues of Rs. 15,883 Cr" ... "T&D") stores one `revenue` row per segment. BAJFINANCE AUM at 31 Mar 2026 thus holds mortgage 1,62,077, consumer 1,04,485, rural 25,234, rural_sales 10,559, sme 51,570, commercial 33,839, auto 15,011, gold 17,831, urban_sales 37,430, las 33,247, 2w3w 4,288+8,325, cv_tractor 3,881, mfi 2,198 and total 5,09,975; KEC FY26 revenue holds T&D 15,883, civil 3,823, renewables 516, cables 2,217, transportation 1,555, oil_gas 258.
- **Segments and entities (T-049, 4 Nov 2026).** A segment word labels a table value only when the row's own label names it, when a text-only heading row above the row starts at or left of the table's first period column, or when the heading sits in the band above the period header and does not start right of that column. A page title ("Novelis, Aluminium and Copper Businesses"), a page footer, and a segment data row ("Copper 673 907 918") therefore no longer label the rows around them: the HINDALCO Q4FY26 / Q1FY27 consolidated EBITDA 11,197 and business-segment EBITDA 10,812 are `total`, not `copper`. In running text a segment word counts only inside the figure's own sentence; a share clause ("63% of our unexecuted order book") may look back 400 characters. KEC FY26 order book is 36,267 `total` and 23,000 `T&D`. `page_basis` reads the entity from the deck page heading ("Financial summary – Bajaj Housing Finance" → `bhfl`, "… – Bajaj Finance" → `standalone`, "Business segment wise AUM - Consolidated" → `consolidated`), so Bajaj's standalone AUM 3,72,986 and BHFL 1,40,706 are tagged instead of being `total` with an unstated basis.
- **Ratio periods (T-107, 8 Nov 2026).** A ratio row (`kpi._RATIO_METRICS`: `roe_pct`, `roa_pct`, `nim_pct`, `cost_of_funds_pct`, `credit_cost_bps`, `ebitda_margin_pct`, `gross_margin`, `contribution_margin`, `adjusted_ebitda_margin_of_gov`, `opex_ratio`, `commission_ratio`, `pat_margin_pct`) takes the period its page prints, not the document's year by default: on a quarterly document a ratio that names no period of its own is the quarter's annualised rate (`sentence_rows(..., ratio_quarter=True)`, set by `extract_company` for every document that is not an annual report and is at most 80 pages), a year named beside the label ("for FY2026", "for the year ended 31 March 2026", "full year": `kpi._year_named`, whose scan stops at the label's line so a table header's bare "FY26" does not count) keeps the year, and a table's column header decides each column as before. The quarter is taken only when `keep_period` allows it, so a stale `FY27` default keeps its label instead of becoming a future Q4FY27 and being dropped; an insurer's ROEV and VNB margin are out of the set (a roll-forward over the year: SBILIFE's 19.7% ROEV is FY26). Cause: BAJFINANCE's Q4 FY26 build stored the highlights table's "ROE 20.0%" (its Q4 FY26 column) as FY26, so "ROE for FY26" answered the quarter's rate instead of the year's 18.1%. Measured on `t113_p10_v2.db` copies: BAJFINANCE `roe_pct` FY26 36 -> 28, Q4FY26 11 -> 19; the ten-company KPI build moves 22 FY rows to Q and loses none (ROE 8, credit cost 8, EBITDA margin 4, ROA 1, cost of funds 1), and `pilot3_ratio` / `pilot3_kpi` answer FY26 ROE 18.1 first (`pilot3_ratio` now serves `stated + derived`, the company's figure before the computed one). Cases in `tests/test_pilot3_kpi_ratio_period.py` (5).
- **Periods (T-049, 4 Nov 2026).** A period printed between the label and its value ("GNPA and Net NPA as of 30 September 2025 stood at 1.24%") is used instead of the document period, so that row is Q2FY26 not FY26; a quarter a later deck reprints for comparison keeps its own period and takes the later document's `known_at`. A prose line laid under a distant table header is not a table row (it used to take that header's column, e.g. Q4FY20 for "as of 31 March 2021"): any row label with a verb (stood, was, grew, compared, against …) is skipped by the table rule, and a value must be a whole token, so "2W" and "B2C" are not read as numbers. A ratio or stock figure dated 31 March (GNPA at "31 March 2025", AUM at "31 Mar 2026") is also stored under its Q4 label (Q4FY25, Q4FY26) beside the fiscal year: the quarter end is the year end, and the quarterly trend question was missing Q4; a flow (revenue, PAT) stays annual only. **A period can never begin after its document was filed** (`kpi.keep_period`, `kpi.period_start`): a row whose fiscal period starts after the document's `known_at` is dropped and counted as `period_after_doc`. The 4 Nov grade found 2019-era filings labelled Q1 FY27 because `June 26, 2019` was read as "June 2026" — the `MON_Y` pattern took the day for a two-digit year (now refused when a four-digit year follows: "June 26, 2019" is no period at all), and the misread date then became the document's default period. A transcript's `known_at` is raised to its call date (O1) before that test, so a call's own rows survive it.
- **Sector lexicon families (loop 3, 4 Nov 2026).** A lexicon file may declare `sectors: [bank, nbfc, ...]`: in a `--profile` build an entry of that file applies only to companies whose profile `sector` is one of them, so an IT company no longer gets `deposits` or `crar_pct` rows; without a profile only the families marked `no_profile: true` (`lenders`, `metals`, `orders`) apply, which keeps the pilot3 three exactly as they were. One file per sector: `bank`, `insurance_life`, `it_services`, `pharma`, `fmcg`, `auto_oem`, `consumer_internet`. An entry may also give `strict` labels (a list of regexes): `sentence_rows` uses them in place of `labels` when present and they require the value right after the term (e.g. `underlying volume growth\b[^.]{0,25}?(?=\d+(?:\.\d+)?\s*%)`), while the table/mix rules keep `labels` — this is how a deck's chart page ("Volume Growth Topline 23.7% Margin …") stops reading a neighbouring KPI's number. Gap quantifiers in a strict label are lazy (`{0,25}?`), never greedy, or the lookahead lands inside a later number. `value_unit` refuses a `$ bn` value for a `usd_mn` metric (the row would store 4,800 where its quote says "4.8 billion") and `finalize_unit` keeps `inr_bn` / `inr_mn` values with their printed scale. A results table's bare dates are relabelled by `relabel_group_columns` from the "Quarter ended | Half Year ended | Year ended" headings above them (30.09.2026 under "Half Year ended" is `H1FY27`), and `page_money_unit` reads a page's "(₹ in billion)" declaration. Measured on the pilot10 copy (`D:\RealityEngine\pilot10\scratch\w_kpi3.db`): A1 651 → 676 of 898, A3 99.85 %, A4 `xbrl_disagreements` 312 vs base 335, `test_pilot3_kpi.py` 45 passed, checkpages 145 (KEC 29, BAJFINANCE 59, HINDALCO 57).
- **KPI fix round (loop 3, T-056, 4-5 Nov 2026).** The sector gate had also deleted rows that are universal: `ebitda` and `roe_pct` moved to `common.yaml` (all sectors), insurer `aum` was added to `insurance_life.yaml`, and `ebitda_margin_pct` keeps its bare `margin` label in `metals.yaml` (metals neg `ebitda`) while `common` keeps the anchored entry. Table rows under a profile now take a column's period from its own header only: `_relabel_columns` assigns each quarter/half-year/year heading a contiguous run of columns centred under it, forced by the column's own date (a half year ends only Sep/Mar, a year only Mar) and by the repetition that starts the year-to-date block (Q2FY27 and H1FY27 both end 30.09.2026; a 31.03.2026 column under "Quarter ended" becomes `Q4FY26`, not `FY26`), and only the first quarter column of a results table is kept. A table value must be a whole printed token (`_whole_printed`: `791.0` inside `7,791.02` is refused; `_comma_decimal`: `0,37` is a decimal comma), a pct at most `max_pct` (100 unless the entry sets it), a day count at least 1, never a signed/negative count-money token, and a row that prints more values than the table has columns is dropped (`st["column_mismatch"]`); `keep_period` also drops rows whose period ends before `profile.window_start()` minus one year (`st["period_before_window"]`), dropping 278 deck-history rows (FY23-FY25 charts). `_unit_from_label` takes a pct only from a label that prints `%` (the "R&D expenditure 23,676" rupees are no longer a percent), and a bare rupee figure on a page that declares its unit keeps it (`page_money_unit` now reads "( in billion)" too, the ₹ glyph often lost: SBILIFE's GWP 1,012.9 is `inr_bn`). The sentence reader refuses a value whose label is on another line with another lexicon label between them (INFY's fact-sheet blocks), reads `from X to Y` as Y and `by N … to/at M` as M (a `by` figure is a change: ETERNAL's 18,288 not 316), refuses `impacted by` / `is an $18 million` / `larger than $50 mn` / `$50 mn plus clients`, and never stores the token after "compared to" as a second period (INFY DSO 67, not 69). Naming: `ebitda`/`roe_pct`/`aum` rows come back for KEC, SUNPHARMA and SBILIFE; the KEC `ebitda` Q2FY27 row is 271 crore ("EBITDA: Rs. 271"). No company names are in the code or the lexicons. Measured on the pilot10 copy: A1 677 of 898 (no company below its baseline; BAJFINANCE 71, ETERNAL 68, HDFCBANK 75, HINDALCO 69, HINDUNILVR 74, INFY 65, KEC 51, MARUTI 61, SBILIFE 75, SUNPHARMA 68), `test_pilot3_kpi.py` 53 passed, checkpages 145 (KEC 29, BAJFINANCE 59, HINDALCO 57) unchanged. The seed-20261105 hand read of 20 new rows per family is still short of 18/20 in most families (a deck's "Sales Volume" row was read as `revenue` until the `volume` neg was added after the read; HDFCBANK `advances` takes a rupee-scale table figure as crore; ETERNAL reads guided/call margins; KEC's `debt equity ratio` sits under `net_debt_to_equity`), so a second label fix round is owed.
- **KPI precision round 2 (loop 3, T-056, 5 Nov 2026).** Five general rules, every one `--profile` only, so pilot3's checkpages rows do not move. (1) After a company's rows are written, `_review_outliers` drops a row above 500x or below 1/500 of its (symbol, metric, unit) group median (groups of 4+; the factor was tuned from 25 because 25 dropped KEC's true `net debt including acceptances` 6,722 crore against a median polluted by small subsidiary figures) and any `pct` row above its entry's `max_pct`, writing symbol, metric, value, unit, quote, doc_key, page and reason to `<out stem>_kpi_review.csv`; `xbrl_segment` rows are never reviewed. Outlier groups on the pilot10 copy fall 28 -> 10 and every named absurd row (HDFCBANK advances 29,371,662,693, deposits 2,044,953, pat 746,712,933; BAJFINANCE gnpa 546,944; SUNPHARMA us_generics 582,201 `usd_mn`; HINDALCO net_debt_to_ebitda 103,515; SBILIFE revenue 24,416,322) is gone. (2) In an annual report, or any document over 80 pages, the document headline is no default period: `sentence_default_v1` takes a period only from the page's own first lines (`doc_default_period([page_text])`), else no row (`st["no_period_long_doc"]`); this removes SUNPHARMA's full-year US sales under Q1FY27. (3) A table row's label owns its value: `_label_owns_value` refuses a value when any word other than a unit, a period token or the entry's own alias sits between the row's label and it (HDFCBANK's side-by-side `Advances | ... | Fixed assets | ...` blocks), and a sector-family row must print a word of its own label in the quote (`_quote_names_label`; common `revenue` keeps label-on-the-line-above rows). (4) The sentence reader under a profile refuses a value led by `driven by`/`due to`, a prior-year clause ("last year we were at"), a fact-sheet column (a blank line or more than two line breaks between label and value), a figure after the label's sentence ends, a range band ("0.9%-1.5%") and forward/threshold wording (`target`, `range of`, `will`, `expected`, `minimum`); `advances` neg gains `capital assets`, `deposits` gains component/trust wording, `crar_pct`/`tier1_pct` gain Tier I+II and Car Finance, `esop_cost` gains director/remuneration. (5) `trillion`/`tn` is a unit (SBILIFE's 5.12 trillion AuM is 512,000 crore), a rupee token never fills a `usd_*` metric (the 582,201 mn "Gross sales" row is gone), and gross `debt[- ]equity` split out of `net_debt_to_equity` into `debt_to_equity`. Measured on `w_kpi5.db` (ten companies, fresh copy of `l3_base.db`): A1 674/898, with BAJFINANCE 70 (baseline 71) and HINDALCO 67 (baseline 69) the only companies below baseline (ETERNAL 68/65, HDFCBANK 75/71, HINDUNILVR 74/71, INFY 65/65, KEC 51/51, MARUTI 61/59, SBILIFE 75/67, SUNPHARMA 68/62); review rows KEC 0, BAJFINANCE 62, HINDALCO 42, HDFCBANK 9, SBILIFE 13, INFY 7, SUNPHARMA 10, MARUTI 13, HINDUNILVR 4, ETERNAL 0; `test_pilot3_kpi.py` 53 passed, `test_pilot3_core.py -m "not slow"` 29 passed, checkpages 314 checked / 145 found (KEC 29, BAJFINANCE 59, HINDALCO 57). The seed-20261109 hand read (20 new rows per company) counts KEC 16, BAJFINANCE 14, HINDALCO 15, HDFCBANK 14, SBILIFE 17, INFY 19, SUNPHARMA 20, MARUTI 15, HINDUNILVR 18, ETERNAL 15 right; the remaining wrong classes are a monthly export/volume figure under a quarter default, a segment/peer-band figure under a total metric, and duplicate periods from one printed row.
- **KPI precision round 3 (T-061, 4 Nov 2026).** Six general rules, no company named. (1) A number the text layer split in two is one number: `_row_string` joins `21` + `,213.89`, `find_values` reads `0. 77%` as 0.77 and refuses `77k`, and a money token printed with a three-digit dot group (`1.953 crore`) is the OCR of 1,953 crore. (2) Units: `lakh` is its own unit (`inr_lakh` = /100 crore, `count_lakh` = x1e5: HINDUNILVR's `2 lakh` direct reach is 200,000), and a bare count keeps `count` unless its own label prints million/lakh/crore (`13.77` under `Loans booked (No. in million)` is count_mn; `approximately 399,000` stays count). (3) Table alignment: values are right-aligned inside their cells, so `_assign_columns` takes the first value's offset as the row's alignment and, when the row prints one value per column, pairs them in printed order (KEC's `0.90` is H1FY26 and `1.00` H1FY27); values are assigned against the full column set and the kept quarter column is chosen after (`_kept_columns`), and a row whose label prints its own period (`FY26 Order intake of 25,280`) keeps it. (4) Subject: `_quote_owns_value` refuses a table quote that crosses another label (`Advances | ... | Fixed assets | 14,645.26`), `_neg_context` keeps a neg word to the label's line (the `%` above `Alumina Production` is not its neg) while still reading `order book \nand L1`, and `_belongs_to_next_label`, `_PAT_OCI` and `_CONSIDERED` refuse a fact-sheet number that is the next label's, PAT+OCI, and an investee's `considered in` figure. (5) Sentence guards apply in every build: plans and ceilings (`another`, `planned`, `up to`, cumulative), a share of another base (`70% of the approved thresholds`), a numbered list/section marker (`4. In Q4`) and a lakh-crore aggregate (`17.15 lakh Cr`); a period after `as against`/`compared to`/`lower than` belongs to the comparative, not to the value. (6) The outlier gate is 100x (median of absolute values, so BAJFINANCE's `nnpa_pct` 77 against a 0.4% group is dropped and KEC's true 6,722 crore net debt kept), and a page that is a monthly sales release or an investee statement (Form AOC-1, `Independent Auditor's Report`) contributes no KPI rows. Measured on `D:\RealityEngine\pilot10\scratch\w_kpi6.db` (fresh copy of `combined2.db`): A1 727/898 — BAJFINANCE 77, ETERNAL 67, HDFCBANK 80, HINDALCO 75, HINDUNILVR 77, INFY 66, KEC 64, MARUTI 76, SBILIFE 74, SUNPHARMA 71; KEC (64 vs 66) and HINDALCO (75 vs 76) finish below their baseline because the new period rules re-dated rows the baseline had counted. The seed-20261111 hand read of 20 rows per company (new rows first, all rows where fewer than 20 are new) scored KEC 18, BAJFINANCE 17, HINDALCO 12, HDFCBANK 16, SBILIFE 16, INFY 5, SUNPHARMA 14, MARUTI 15, HINDUNILVR 12, ETERNAL 16 of 20: only KEC meets 18/20, so the round fails its precision target. Remaining families: an unlabelled segment table's revenue rows (INFY), a gross/net-debt table read as `net_debt_to_ebitda` (HINDALCO), flow changes (`↑₹0.78 tn`) and segment figures stored as total levels, and a segment percentage stored as the company margin (HINDUNILVR 4%). `test_pilot3_kpi.py` 66 passed.
- **KPI three faults: segment totals, debt ratios, flow periods (T-064, 4 Nov 2026).** Three general rules, no company named. (1) Table shape: a row that prints more values of the entry's kind than the chosen header has columns is not that header's row (the `row_cand` count in `table_and_chart_rows`); a segment table that prints "Revenue" over nine business-segment columns under a two-date caption no longer gives the company's revenue. A block heading that joins the row string does not own the row's value: `_own_row_hits` keeps the metric whose label starts last ("Leverage Net Debt" is the net-debt row, not the leverage ratio), while overlapping aliases of one word ("Revenues" matches `^revenue` and `^revenues?`) keep every hit. (2) A flow over the year gets no Q4 twin: `_q4_twin` now twins only `_STOCK_METRICS` (balance-sheet levels and ratios: net debt, AUM, order book, deposits, GNPA/NNPA, CAR, CASA, DSO, working-capital days), so an FY26 ROE or EBITDA margin is not also Q4 (money flows such as PAT and loan-loss provisions are not stock levels either). (3) A direction word without a level link is a change, not a level: `_DIRECT_CHANGE` refuses "DSO is down 2 days" (2 is the change; 67 days is the level) while "reduced to 134 days" keeps the value; a shorter alias of one label is skipped under its longer form ("EBITDA as a %" under "EBITDA as a % of TO"), and `_belongs_to_next_label` strips the newline before the next label so a dashboard's "EBITDA as a % of TO / 4 %" stores no neighbouring growth figure as the margin. (4) A number glued to a known unit is one value: `find_values`/`_value_matches` accept "4.5x" and "25kt" (the suffix is the unit) while "2W" and "77k" stay refused; this restores the ratio sentences the whole-token guard had started to drop. Five new cases in `test_pilot3_kpi.py`.
- **KPI branch line: period qualifiers and a hedge (T-066, 5 Nov 2026).** Two general rules, no company named, `kpi.py` only. (1) "YTD" / "year to date" / "till date" / "to date" are period qualifiers, not plan words: they say which period a value belongs to (a first quarter's YTD intake is that quarter's intake, and an order book is a stock), so they left `_PLAN_LEAD` and a value printed with one is stored; `_ytd_period` then dates a YTD *flow* to the period its document reports (Q2 -> H1FY, Q3 -> 9MFY, Q4 -> FY, Q1 unchanged) while `_STOCK_METRICS` keep their date, so "YTD order intake of Rs. 16,050 crore" in a Q2 release is H1FY26 and "YTD Order Book of Rs. 39,325 crore" stays Q2FY26; T-073 adds the filing-date rule: when the document was filed after the quarter ended and its own sentence names no period, the flow is year-to-date **as of the filing date** (`fiscal_period='YTD'`, `as_of_date` = filing day), so a later release's "YTD order intake" cannot overstate the half, while an explicit half-year phrase keeps H1. (2) "would" is a hedge on a level the management states ("the EBITDA per ton ... would be north of $1,000"), not a plan, so it left `_FORWARD`, while "will" still marks a commitment ("capex will be INR2,000 crore"). Restores KEC's order intake 6,303/6,300 (Q1FY27) and order book 36,267 (FY26/Q4FY26) and 39,325 (Q2FY26), and HINDALCO's EBITDA per tonne 1,000 USD; `checkpages run` 145 (KEC 29, BAJFINANCE 59, HINDALCO 57) with 13 rows added on the 314 checked pages and none removed, `test_pilot3_kpi.py` 72 passed, A1 728/898 on `w_kpi8.db` (KEC 64, HINDALCO 75).
- **KPI goal-brief round (T-079, 5 Nov 2026).** One round run from the goal (18 of 20 hand-read rows right for INFY and HINDALCO, no company two rows worse) with no edit list; every rule is general, no company name in code. On a `sqlite3` backup of `pilot10.db` (`D:\RealityEngine\pilot10\scratch\w_t079.db`) all ten companies were rebuilt once (`--part kpi`, 228 s). (1) Unit: a table's own caption states its currency — `_usd_unit` reads "In US$ million" / "(Dollars in millions)" at or within 150 px above a row, so INFY's US$ statements are `usd_mn` while the rupee statement above them stays crore. (2) A contractual commitment is not capex ("... contractual commitments for capital expenditure of $141 million"), and a value followed by "arising from / pertaining to" is a component, not the total. (3) An auditor's "Other Matter" paragraph (branches, subsidiaries, joint ventures, a trust), a "share of ... associates and joint ventures" figure and a comparative label ("compared to a net income of $110 million") are not the company's; `_SENT_END` no longer cuts a sentence at "Rs."/"No."/"Ltd.". (4) "For the first nine months" / "six months ended 30 Sep 2025" date the figure's own span (`_frame_period`: 9M/H1 of the stated fiscal year). (5) Periods: "Third Quarter Fiscal Year 2026", "Quarter 4 (January-March), FY2025-26" and "Q2 (July-September), FY 2026-27" are quarters; OCR "04 FV26" is Q4FY26; a bare "Q4" right after a value is the document's fiscal year; "as of 31 Mar 2026 and 31 Mar 2025 was V and V" pairs the first value with the first date; a group heading on the results header row itself ("3 months ended | Year ended", digits included) relabels its own columns, and a single heading covers every column. (6) A bare year token ("Particulars 2026") and a footnote marker "(3)" are never money levels; "by" plus an OCR rupee glyph ("AUM grew by z 20,811") is a change, not the level; a TTM row is not a quarter's, and a table's own "EBITDA" row wins over its "Business Segment EBITDA" sum. (7) Entity: a page titled by a subsidiary's release ("Novelis Reports ...") sets `basis`, and a nearby "<Name> Limited" that is not the reporting company's own name sets the dimension; the company's own title is skipped by symbol and profile name. Measured: `checkpages run` 145 (KEC 29 / BAJFINANCE 59 / HINDALCO 57); A1 759/898 with every company exactly at the live level (BAJFINANCE 79, ETERNAL 72, HDFCBANK 84, HINDALCO 77, HINDUNILVR 81, INFY 72, KEC 64, MARUTI 81, SBILIFE 76, SUNPHARMA 73); `test_pilot3_kpi.py` 79 passed. Hand read on the copy: before (seed 20261105) 124 of 200 — KEC 13, BAJFINANCE 16, HINDALCO 9, HDFCBANK 14, SBILIFE 16, INFY 7, SUNPHARMA 15, MARUTI 13, HINDUNILVR 15, ETERNAL 6; after (seed 20261109) 134 of 200 — KEC 14, BAJFINANCE 12, HINDALCO 13, HDFCBANK 11, SBILIFE 17, INFY 18, SUNPHARMA 12, MARUTI 18, HINDUNILVR 16, ETERNAL 3. INFY reaches 18/20; HINDALCO does not, and BAJFINANCE (-4), HDFCBANK (-3), SUNPHARMA (-3) and ETERNAL (-3) fall behind their before read. Rows that stop the target: BAJFINANCE's BFSL/BHFL/Bajaj Broking slides (an abbreviated subsidiary name is not a "<Name> Limited"), HDFCBANK's CASA column periods and HDBFSL/industry figures, SUNPHARMA's net-cash sign and a subsidiary's revenue, ETERNAL's acquisition cash stored as net debt, a spend stored as a count and segment margins, HINDALCO's "Adjusted free cash flow before capex" stored as capex and segment-table dimensions. A self-inflicted regression is named here: a "Statutory Reports" section heading makes `page_basis` return "statutory" on 8 sampled rows across HDFCBANK, SUNPHARMA, MARUTI and ETERNAL; the fix is a stoplist of report-section words in that title rule, left for the next round. Evidence: `.tmp/kpi_before.tsv`, `.tmp/kpi_after.tsv` (row, quote, verdict, why).
- **KPI goal-brief round 2 (T-079, 5 Nov 2026).** The four regressions of round 1 were the classes below, not noise. `page_basis` now requires a release title to carry a release phrase after the verb ("<entity> Reports <quarter|financial|results|press|earnings>"), so a "Statutory Reports" section heading is no longer an issuer; the entity words (BFL/BHFL/BFSL/HDBFSL/Bajaj Broking) moved out of `kpi.py` into the new `lexicon/page_entities.yaml`, and "Q3 FY26 Executive summary - BFSL" / "Bajaj Broking's performance highlights" name the reporting entity. "Net cash of $3.2 bn" is stored as negative `net_debt` (a transaction's "net cash acquired on acquisition" is still refused), "adjusted free cash flow before capex" is not capex, a mix table's title needs a mix word (`by|wise|mix|split|composition`), a value followed by "Market Capitalisation" is not the metric, a title "quarter ended 31 March" makes the document default Q4 rather than FY, a short line of >=3 numbers is a table row not a sentence, and a percentage whose 300-char window names two or more segments is the group's margin (one segment: that segment's). On `w_t079.db` (one build, 238 s): `checkpages run` 145 (29/59/57), A1 759/898 with every company exactly at live, `test_pilot3_kpi.py` 82 passed. Same-seed read (seed 20261105, the rows still present; removed rows counted separately): KEC 13 right (5 wrong removed), BAJFINANCE 18 (0), HINDALCO 10 (3 wrong + 2 right removed), HDFCBANK 14, SBILIFE 16, INFY 12 (7 wrong + 1 right removed), SUNPHARMA 16, MARUTI 13 (2 wrong removed), HINDUNILVR 16, ETERNAL 10 (4 wrong removed) — 21 wrong and 3 right rows removed, no company below its before read. Fresh-seed read (20261111): KEC 17, BAJFINANCE 16, HINDALCO 15, HDFCBANK 15, SBILIFE 14, INFY 17, SUNPHARMA 16, MARUTI 16, HINDUNILVR 19, ETERNAL 15. HINDALCO still does not reach 18 and MARUTI is one short of 17; the stopping rows are listed in the blueprint. Evidence: `.tmp/kpi_same_seed.tsv` / `.tmp/kpi_same_seed_judged.tsv` and `.tmp/kpi_fresh.tsv`.
- **KPI goal-brief round 3: eight regressions of the branch (T-079, 5 Nov 2026).** One rule round on a fresh `sqlite3` backup (`D:\RealityEngine\pilot10\scratch\w_t079b.db`, all ten companies built once), no company name in code. `kpi.py` + `lexicon/consumer_internet.yaml` + `test_pilot3_kpi.py`. (1) Abbreviations are whole words: `_ABBREV` uses `(?<!\bRs)`-style lookbehinds, so a plurals' "rs"/"no"/"co" no longer hides a sentence end ("quarters. Vimal", "factors. The Company") while "Rs. 1,436 crore. Next" still splits only after crore; `_sentence_bounds` now runs `_SENT_END.finditer(text)` and stops at the first match at/after `pos`, because `finditer(text, 0, pos)` could not see the capital at `pos` for its lookahead. (2) A bullet mark at a line start (`_BULLET_MARK`, `•✓▪►`) is a sentence boundary, so a segment word in another bullet cannot label a figure; when the bullet sentence names no segment, `_block_heading_dim` reads the block's own heading (the trailing heading when the bullet is the block's last line, else the nearest heading above it, with `\d+.` numbering stripped), and an entity page's overview bullets stay the entity's (their dim is `total`, then `page_basis`). (3) `_entity_before` only accepts the paragraph's subject: a `Limited` name followed by its predicate (`is|are|has|in which|reported|...`) or a block-heading quarter, searched within the blank-line paragraph and 600 chars before the label, nearest first; an address block or a passing mention ("stake sale in subsidiary HDB Financial Services Ltd, Other Income grew") no longer gives an entity. The abbreviated-name fallback (`page_entities.yaml`: BHFL/BFSL/HDBFSL/BFL) is unchanged. (4) `page_basis`' one-word-quarter title ("<word> Q3FY26") needs an earnings/results/presentation/call word after the quarter and refuses a section word from `_SECTION_WORDS` (metrics, "results", "highlights", "snapshot", "company", ...), so "Novelis Q3FY26 Earnings" is `novelis` while "Revenue Q3 FY26", "Highlights Q2FY26", "Results Q2 FY26" and "Company Q2 FY27 Earnings Conference Call" are not issuers. (5) `VAL_RX` starts only at a token boundary (`(?<![A-Za-z0-9])`), so "A320 deliveries", "B737 orders" and "A32071" yield no number and 1,200 / INR2,000 / 21,213.89 stay whole. (6) `_FRAME`'s `H1` is refused when a comma or digit follows it: "Net Revenues: H1,91,218.60 crore" is the OCR of the rupee sign, so HDFCBANK p83 NNPA 0.38 and ROA 1.94 (and CAR 19.7, ROE 14.3) are FY26, not H1FY26. (7) `_PROSE_ROW` includes is/are/has/have/had, so the short-line table guard keeps prose: SBILIFE's "APE channel mix for 9M FY 26 is bancassurance channel 62%, agency channel 27% & other channels 11%" is a sentence again (banca 62 9MFY26, 53 H1FY27, 47 Q1FY27, 60 FY26). (8) `segment_revenue_rows` stops its heading search at a blank line, so a bullet block's heading cannot be the next section's title; `consumer_internet.yaml` gains "adjusted revenue" as a strict sentence label, so ETERNAL's "At a consolidated level, Adjusted Revenue grew ... to INR 16,692 crore" is a sentence row (`total`, Q3FY26) and 17,680 FY26 is `total` too (the Q1/Q2 letters add 20,648 and 24,621). Measured on `w_t079b.db`: `test_pilot3_kpi.py` **90 passed** (eight new real-text cases), `checkpages run` **145** (KEC 29 / BAJFINANCE 59 / HINDALCO 57), A1 **759/898**, every company exactly at live; row counts 2,070→2,065 BAJFINANCE, 189→192 ETERNAL, 671→672 HDFCBANK, 709→710 HINDALCO, 572→566 KEC, 703→707 SBILIFE (others unchanged). Collateral reported in the blueprint: the BAJFINANCE strategy page's MFI/2-Wheeler AUM 2,317/6,220 are `total`, nine wrong `mortgage` BAJ rows are `bhfl`/`total`, HDFCBANK's OCR "HOB Financial Services Limited" rows read `hob_financial_services`, and eight HINDALCO Novelis rows whose segment word was in another sentence are `total`. No new `typecheck` errors.
- **KPI wrong-class round (T-081, 5 Nov 2026).** One rule round on the six classes Opus read on `w_t079b.db`, one 10-company KPI build on a `sqlite3` backup (`D:\RealityEngine\pilot10\scratch\w_t081.db`), every rule general and no company name in code; company words stay in `lexicon/`. (1) Sign: `_NEG_LEVEL` stores "was a loss of $160 million" and "net debt is minus INR6,000 crores" negative. (2) Entity: `_entity_before` reads the nearest legal-name heading before or after the paragraph (an annual-report box prints the investee heading after its text; an all-caps address line followed by a street is not one, `_entity_heading`), and `lexicon/page_entities.yaml` names the entities a heading prints ("Subsidiaries – Q2FY27 update – HDB Financial Services") or a sentence starts with ("HDFC ERGO has ..."); a document that names an entity on its first pages passes that basis to its continuation pages (`doc_basis`). `find_dimension` reads the segment that opens the block ("Hyperpure - Revenue grew", "Novelis recorded shipments") inside the figure's paragraph, and a deck bullet may look further back for a heading-only line ("Novelis*"); a line naming two or more segments is a legend, not a subject; a margin's two-segment rule reads its own paragraph; a table's page caption ("Hindalco (India) Business : Key Financials") names the business the table reports. (3) Period: a period before the label counts only inside the label's sentence; a quarterly cue ("quarterly", "QoQ", "previous quarter", a line-start "March Quarter" or "Quarter 4" heading) dates a year-to-date flow to its closing quarter (H1->Q2, 9M->Q3, FY->Q4); "improved to X from Y in Q3" dates X to the quarter after the comparative; a two-column "A v/s B" table pairs the nth label occurrence with the nth pair; "During FY 2025-26" frames the sentences that follow; an ascending chart axis (FY24-25 / FY25-26) takes the later year. (4) Revenue: `sales of investments`, `sales promotion`, `revenue from sale of goods/services` are not revenue; a table row whose matched label belongs to the neighbouring table on the same text line is refused by the quote-at-the-row guard (`_quote_has_metric`), and a bare "Revenue" row under an R&D caption is refused. (5) An analyst's question ("take back market share to 50%?") is not a KPI; "Capex per store" is not capex; a count in a use-of-proceeds/prospectus table is not stores; "cumulative ... crossed 50,000 units" is a milestone; a bare count printed with decimals is an amount. (6) `_INVESTEE` matches the investee phrase across a slash ("financial statements/ financial results of eight subsidiaries"). Lexicon: `common.yaml`, `lenders.yaml`, `bank.yaml` (book value per share unit `inr`), `dimensions.yaml` (India Business), `page_entities.yaml`, `auto_oem.yaml` (network inventory). Results: `test_pilot3_kpi.py` 97 passed, `checkpages run` 146 found (KEC 29 / BAJFINANCE 59 / HINDALCO 58), A1 759/898 (BAJFINANCE 78 against its live 79; the other nine at or above). The rows of the ticket and the rows these rules move or drop are in the T-081 blueprint bullet.
- **T-164 measured (round 6, 11 Nov 2026).** u8: 24,329 statements, 'other' 33.6% (main baseline 36.2%; per company
  30.9-37.8% vs 31.1-40.6%); q12: 39,261 statements, 'other' 36.2% (main 38.6%; per company 30.4-41.7% vs
  32.7-44.3%); the statement multiset is identical to a main-code rebuild on both stores (0 differences). Seed-6164
  samples: entity precision 86.4% u8 (57/66 tokens) and 86.4% q12 (57/66), topic label precision 90.8% u8 (69/76) and
  89.5% q12 (68/76); Dahlias tagged in 122/122 statements that mention it (was 19/122), Summit Plaza 11/11, Aureva 2/2,
  Bengaluru 32/32, Secunderabad 91/96. Recall on 25 empty-entity statements per store is still weak: 9 statements name
  a required entity and all 9 are untagged (Delhi Metro, Tata Coffee, Middle East, Tata Gluco+, India Beverages,
  Pollution Control Board, Department of Telecom, Tata Group, Skanray), and RBI is tagged in 1 of 67 statements that
  mention it. Artifacts `.tmp/t164/r6_entity.csv`, `r6_recall.csv`, `r6_topic.csv` (statement text + right/wrong per
  item). Tests: transcripts 12, speakers 8, kpi 114, no-company-literals 7, guidance 32, answer_check 25,
  doc_identity 21, profile 8, lookups 50 + 1 skipped.
- **KPI period round 4 (T-081c, 5 Nov 2026).** `reality_engine/pilot3/kpi.py` + `reality_engine/tests/test_pilot3_kpi.py`: one rule round on the two period classes Opus read on `pilot10.db` (a call figure dated to the year, a deck row dated to the comparison quarter), one 10-company KPI build on a `sqlite3` backup (`D:\RealityEngine\pilot10\scratch\w_t081c.db`, 6,054 rows against 6,042), no company name in code. (1) `_CMP_BPS` + `_bps_value_period`: a bps amount followed by a comparator link ("an improvement of 27 bps over Q1 FY26", "reduced 4 bps over Q3 FY26") makes that quarter the *comparative*; the value is the quarter after it (rolling into the next fiscal year at Q4), except a year-on-year comparative (same quarter, previous fiscal year: "up 27 bps over Q2 FY25" in a Q2FY26 deck), where it is the document's own quarter. The comparative no longer enters `cand`, and a fallback resolves the value's quarter from the comparative and the default period, so a long deck whose page default is a stale "Q3 FY25" still gives Q3FY26. (2) A year phrase dates a figure only when the figure's own sentence names no quarter: `_QUARTER_CUE` (`in Q2`, `sequentially`, `QoQ`, `quarter ended`, `previous quarter`, the worded quarter names) gates the `_FY_FRAME` branch of `_frame_period`, so a call's "improved by 27 basis points in Q2 ... came in at 7.52%" stays Q2FY26 and "came down sequentially ... 7.31%" stays Q2FY27 instead of taking a prior sentence's FY. The `lq` step at the period read (`\bin Q([1-4])\b`) was not the cause: it fires and `_frame_period` then overwrote the quarter from the earlier sentence's year phrase. A figure whose own sentence names no quarter keeps the year phrase (`run rate of about INR 10,000 crores a year` under an earlier "for FY26" frame is FY26). (3) `_PLAN_LEAD`'s 90-char look-behind stops at the label's sentence start, so "should come back to double-digit growth" in the prior sentence no longer drops the Q4FY26 call's "improved by 4 basis points in Q4 ... 7.41%" row. (4) `_ytd_period` names a Q4 year-to-date flow `FY26`, not `FYFY26` (it appended the whole "FY26" capture group to "FY"). Evidence on `w_t081c.db`: BAJFINANCE `cost_of_funds_pct` 7.52 Q2FY26 (call `0a3c2353` p4), 7.31 Q2FY27 (call `3edbe0c3` p4), 7.41 Q4FY26 (call `8883ebf2` p4, a row the old build dropped), deck rows 7.52 Q2FY26, 7.45 Q3FY26, 7.41 Q4FY26, 7.40 Q1FY27 with the subsidiary pages 7.38/7.30/7.28 on the same quarters, and KEC `order_intake` 16,000 FY26 (was FYFY26); no `FYFY` label remains. `test_pilot3_kpi.py` 102 passed; `checkpages run` 146 (KEC 29 / BAJFINANCE 59 / HINDALCO 58; the fixture baseline is 145), A1 760/898 with BAJFINANCE 79 (from 78) and no company below its `a1_rebuild.json` count. Period-level diff against `pilot10.db`: 14 rows moved, 1 duplicate dropped, 0 added — BAJFINANCE call figures dated to the call's quarter (GNPA/NNPA 1.01 Q4FY26, provision coverage 60 Q4FY26, customer franchise 110.64 Q2FY26 and 124.43 Q1FY27, AUM 462,261 Q2FY26, deposits 69,766 Q2FY26), KEC `order_book` 1,200 FY27 -> Q1FY27, KEC EBITDA margin 7.1 FY26 -> Q4FY26, HINDALCO gross debt 12,200 (`india`) / 75,000 (`novelis`) FY26 -> Q4FY26 (a stock level that now carries the quarter label, not the year), SUNPHARMA market share 8.5 FY26 -> Q1FY27. The one dropped row is KEC p12's "EBITDA Margin at 7.1% against 6.9%" FY25 comparative, whose same figure survives as Q4FY25 on p2 and in the p18 table. Left as before, no rule: MARUTI 538,994 domestic volume stays FY26. `pilot10.db` itself was not rebuilt (read-only data root); the controller runs the same build to move the live rows.
- **`transcript_statement`**: one row per sentence of management speech (md, ceo, cfo, mgmt, ir) with speaker, role, section (prepared|qa), topics (comma list, `other` if none), period_discussed and period_source (sentence|call), numbers_json (value, unit, period, raw), statement (whitespace-normalised), quote (literal slice), is_fragment (cut by a page break; stored on the page where it starts), named `entities` (capitalised multi-word spans and all-caps/hyphenated names that pass a name cue — a following org/programme/place noun, a possessive, "from X"/"with X", a verb of agency — and are not a metric, a business abbreviation such as BFSI/TCV/ARPOB/HR/SEZ, or a phrase also written in lowercase in the same call; person names from the participant block, colon marks, titles, honorifics and direct address ("I'll ask Rakesh") are excluded; a comma next to one occurrence never drops a name for the whole call; single names after a preposition, a comma or before a place noun are kept for recall; longest span wins per statement; T-164 r6) and `answer_turn` id grouping the sentences of one management answer (T-164). Analyst questions are stored separately in `transcript_question` with an `analyst_question`/`analyst_questions` view. Analysts and moderator are not stored in `transcript_statement`; speakers who cannot be classified are counted in the run summary and not stored. Cover-letter text before the first real speaker is dropped. **Speaker rules (T-056 loop 3, 4 Nov 2026).** Three rule families place a speaker, no company name in code and `lexicon/topics.yaml`'s `people` untouched: (1) a **participants block** on the first three pages — a heading line (`CORPORATE PARTICIPANTS`, `Management representatives:`, `ANALYSTS`, `JOURNALISTS`) then name/title pairs, or a one-line "1. Name – Title"; management titles go through `_title_role` (cfo / md / ir / mgmt) and a name under an analysts/journalists heading is an analyst, never stored; a document label in the block ("Investor Call Transcript") is not a person; (2) the moderator's **"we have with us today A, B and C"** sentence names the management team; (3) **bare name lines** (2-4 capitalised words, no colon) are speaker marks only when the document has fewer than five real colon marks — the six colon-style transcripts never enter that path — and then only for a name in the participants block or a name line repeated 3+ times with speech after it (a participant's name followed by its title is not a mark). In the Q&A a name that answers right after an analyst three or more times, and was never introduced as an analyst, is `mgmt` (`after_analyst`); everyone else stays `unknown` and is only counted in `unknown_speakers`. A running footer whose page number changes is boilerplate (`boilerplate_lines` normalises digits before the repeat count), so it is masked and never enters a quote; and a media call has no moderator, so the moderator-keyed Q&A marker never fires — when a document has no moderator, the first participants-block journalist/analyst opens `qa` (4 Nov review). **Measured on the pilot10 copy:** ETERNAL 691 rows over 4 documents (Akshant Goyal cfo 474, Albinder Singh Dhindsa md 179, Kunal Swarup mgmt 38; Vijit Jain and Aditya Soman not stored), INFY 2,478 over 4 (Salil Parekh md 1,360, Jayesh Sanghrajka cfo 831, Rishi Basu mgmt 232, Nandan Nilekani mgmt 55), KEC 1,803 (unchanged); the participants block also recovered HDFCBANK's Keki Mistry (+102) and Kaizad Bharucha (+63), HINDALCO's Steve Fisher (+447) and SUNPHARMA's Dilip Shanghvi (+214) and Kirti Ganorkar (+58), because their names were never in the lexicon. BAJFINANCE, HINDUNILVR and SBILIFE are byte-for-byte unchanged; MARUTI stays 0 (its five `concall_transcript` filings are one-page cover letters). **Input (3 Nov 2026):** the transcript extractor reads the same documents as `kpi.py` — the pilot3 db's own `doc_page` when the `pages` part has built it (pages.db documents and their RapidOCR text, doc keys already the pilot3 ones), else the sandbox `docs`/`doc_text`. Reading only the sandbox had left `transcript_statement` on the sandbox's calls — 16,189 rows in all, with BAJFINANCE's newest call 2024-02-03 (925 rows) and HINDALCO's 2024-02-20 (971) while the held transcripts run to 2026-08 (KEC's sandbox does hold its 2026 calls: 14,293). With the pilot3 pages it holds KEC 14,294 rows over 63 documents, BAJFINANCE 4,626 over 22, HINDALCO 4,559 over 17 (23,479 in all). **Speaker turns:** a management introduction may carry a composite title ("Mr. Rajeev Jain, Vice Chairman and Managing Director", "Mr. Sandeep Jain, COO and CFO") — the words before the role are allowed; a known name is matched through an OCR slip or a short form ("Stish Pai" = "Satish Pai", "Dev Ahuja" = "Devinder Ahuja") when the surname agrees and the first name is a prefix or 0.8-similar. **Call period:** the "FY 2026 fourth quarter" / "fourth quarter of FY 2026" forms were read with the groups swapped (a `KeyError`); they now give `Q4FY26`.
- **Known limits (measured 4 Nov 2026, with `--pages-db`).** 37,213 rows (KEC 7,179 / BAJFINANCE 19,084 / HINDALCO 10,950; 35,588 on 3 Nov: the prose-as-table rows are gone and the mix/chart/business-revenue rules add their lines); 6,494 of them FY25-FY27 on 3 Nov. Generic labels (`margin`, `ebitda`, `revenue`) over-match in text-heavy pages, so read the confidence tier; a segment is reliable where the row's own label, a heading row or the figure's sentence names it (table, donut and business-revenue pages); `needs_ocr` pages (110 / 361 / 1,181 with pages.db) are extracted only after `pilot3.ocr` has read them and `--ocr-db` is passed.
### O3. pilot3 document collection (T-049)

`reality_engine/pilot3/docs_collect.py` (no model, no OCR, read-only on every store) collects every held document of KEC, BAJFINANCE and HINDALCO as dated page text for the pilot3 core database. The T-048 sandboxes held only `pilot60_history` (newest page 2024-03) and the BSE feed; the real store is wider.

```bash
python -m reality_engine.pilot3.docs_collect --out D:\RealityEngine\pilot3\pages.db [--symbols KEC,BAJFINANCE,HINDALCO] [--coverage <xlsx>]
```

- **Where it looks.** Folders named by NSE symbol or BSE code anywhere under `D:\RealityEngine\raw` (three levels: `pilot60_history\<SYM>\<bucket>`, `annual_report\<SYM>`, `deck\<SYM>`, `material_announcement\<SYM>`, `decks\bse\<code>`, `nse_announcements\*\attachments\<SYM>`), the legacy pile `D:\RealityEngine\pdfs\<SYM>\<TYPE>` and the old `reality_engine\data\pdfs|decks`; plus the sha256-named folders (`decks_full`, `concall_pdfs`, `kec_transcripts`, `results_pdfs`, `results_notes_refetch`, `deck_page_text`), where a file is taken only when its name (= its sha256) is a hash the stores record for one of the company's ISINs (`corporate_documents.sha256_hash`, `deck_sources`, `deck_figures.pages`, `ar_docs`, `raw_documents`). Every ISIN of `symbol_isin_history` (truth snapshot, else the store copy) is used, so BAJFINANCE's ISINs before and after 2025-06-16 both count. The same bytes filed under several announcements (a results PDF comes with the board-meeting outcome and again with the results filing) make one `doc` row dated by the earliest dissemination; every filing (NEWSID, attachment, `known_at`) is listed in `source_record.filings` and every path in `source_record.paths`. `doc_type` comes from what a store says about the exact file (sha256), else the BSE sub-category, else the folder; an `announcement` under the AGM sub-category with 100 pages or more is retyped `annual_report` (`retype_agm`).
- **Dating (filing records only).** The company site's transcript manifest (KEC), `bse_announcements.ann` by NEWSID or attachment name (the GUID in the file name), `corporate_documents` by sha256 / `bse_newsid` / id, `deck_sources`, `ar_docs`, `pilot60_history\manifest.csv`, NSE announcement jsonl. `doc.known_at` is the raw dissemination timestamp (`DissemDT`); the 15:30 IST day shift is the core builder's job. `doc_date` is the crawl date and is never used. A file no record dates keeps `known_at` NULL and counts as undated. `doc.isin` is the ISIN valid on the filing date. **A transcript cannot be known before its call** (T-049 review, 4 Nov 2026): the collector keeps the filing record as it reads it (except a re-filed old transcript, which the next bullet dates by its own printed call date), and the pilot3 build raises both dates to the call date printed in the document (`call_dates.py`, applied in `registry.build_doc`/`build_pages`, so `doc`, `doc_page` and every row derived from them inherit it; the KPI extractor applies the same clamp to its own transcript rows). A call date more than 400 days after the stored date is refused (a stray header date), and only the first three pages are read, so a dated comparison in the body never moves a document.
- **The first pages correct the record (T-161/T-159, 10 Nov 2026).** `reconcile_doc` runs at the end of `collect` and `collect_manifest` on the pages 1-3 text just stored. A document of 3+ pages whose first pages `doc_identity.classify_type()` reads as a transcript *and* which print the call's own moderator line (`doc_identity.moderator_line`; a call intimation's "followed by a Q&A session" is not enough) becomes `doc_type='transcript'` whatever the BSE category, with the record's type kept in `source_record.record_type`. A transcript whose printed call date (`call_dates.call_date`, the reader the build already uses) is more than 120 days *before* `filing_date` takes that date and `<date>T23:59:59`, with `source_record.date_source='printed'` and `record_filing_date`/`record_known_at` kept for audit; only pages 1-3 are read and a date is never moved later. The date rule is a transcript's only: a results PDF prints its period end (SAIL 2021-10-29 prints 2021-06-30) and a deck its period start (a HINDALCO Q4 FY25 deck filed 2025-11-21 prints "April 1, 2025"). `python -m reality_engine.pilot3.docs_collect --measure [--stores a.db,b.db]` prints, read-only, every document the rules would re-date and re-type (default `p20/p20new.db`, `u8/u8.db`, `q12/q12.db`, `pilot10/pilot10.db`); on 10 Nov 2026 it measured 0 re-dated and 15 re-typed (p20 7, u8 4, q12 4, pilot10 0). `stat["redated"]`/`stat["retyped"]` count them per company in a build.
- **Tables in `pages.db`.** `doc(doc_key, symbol, isin, doc_type, title, filing_date, known_at, source_path, sha256, pages, source_record, known_at_source)` and `doc_page(doc_key, page, text, method, known_at)` with the FTS5 index `doc_page_fts`: the sandboxes' `docs` / `doc_text` columns plus `symbol`, `isin`, `source_path`, `sha256`. `method` is `script_text` (PyMuPDF text layer, 50 characters or more) or `needs_ocr` (empty text; `pilot3.ocr` reads those pages and `build --part ocr`, or an explicit `build.py --ocr-db`, copies the result into `doc_page` as `ocr_rapid`). A re-run skips a document whose sha256 and pages are already stored. `doc_type` is one of `annual_report`, `deck`, `transcript`, `results`, `press_release`, `announcement`, `audio_link`, `other`.
- **`DOC_COVERAGE.xlsx`** (beside `pages.db`). `summary`: per company and type, documents, pages, `needs_ocr` pages, undated, newest filing date and `known_at`. `missing`: the FY25 and FY26 annual report; for Q1 FY25 to Q1 FY27 the results filing, investor deck and earnings-call transcript; announcements newer than the newest held document; BSE announcement attachments whose headline is held but body is not. `fetch_worklist`: each such headline with NEWSID, attachment and date. `runs`: counts per run, appended.
- **Fetching what is missing** uses the existing fetcher only: `python -m reality_engine.scripts.fetch_pilot60_history --fetch --universe D:\RealityEngine\pilot3\universe3.csv --window-start 2024-04-01 --window-end 2026-10-20`, with `REALITY_DATA_ROOT` set to the main checkout's `reality_engine\data` (a worktree's data folder is empty). It writes `raw\pilot60_history\<SYM>\<bucket>\<newsid>.pdf` and appends to `pilot60_history\manifest.csv`; the next `docs_collect` run picks the files up. When the BSE API refuses a page (HTTP 400; PERSISTENT 2024 at page 6, TATACONSUM 2025 at page 2, INDHOTEL 2024 at page 1, 9 Nov) `api_rows` fetches that window again as two halves, down to two-week windows. A new company set needs this fetch (with `--universe <csv>` and the profile's window) before its profile's `raw/manifest.csv` can exist; `docs_collect` fails without it. Its routine-skip rule (loss-of-certificate, Reg 74(5), newspaper, trading-window and PIT-code notices) is why those headlines stay in `fetch_worklist`.
- **State, 3 Nov 2026** (`pages.db`, `DOC_COVERAGE.xlsx` under `D:\RealityEngine\pilot3`): KEC 621 documents / 5,454 pages, BAJFINANCE 629 / 9,391, HINDALCO 749 / 8,412; 958 of 23,257 pages are `needs_ocr`. Newest `known_at`: BAJFINANCE 2026-10-19, KEC and HINDALCO 2026-10-16. What remains in `fetch_worklist` (46 / 117 / 152 headlines) is the routine notice types the fetcher skips on purpose, plus one KEC large-corporate disclosure, one BAJFINANCE record date and 8 text-only announcements with no attachment. Not held because not yet filed or not in any feed: Q2 FY27 results, deck and call for all three, and the BAJFINANCE/KEC/HINDALCO announcements after 28 Sep / 16 Oct 2026 (the BSE feed in `bse_announcements.db` ends there; NSE announcement records exist for none of the three).
- **Test:** `reality_engine/tests/test_pilot3_docs.py` (fixture stores and PDFs: dating, dedupe, `needs_ocr`, FTS, idempotence, coverage workbook, and the printed-pages rule end to end) and `reality_engine/tests/test_docs_collect.py` (the printed-pages rules as pure text: the six misdated q12 calls, the moderator gate and the cases that must not change).

### O15. Annual-report note tables: ratings, concentration, related parties (T-091, 6 Nov 2026)

`reality_engine/pilot3/notes.py` fills three tables from `doc_page` text only, for any listed company: no company
name, page number or per-company rule in code (wording in `pilot3/notes_lexicon.yaml`), no model, no network. Build
part `notes` (after `pages`; honours `--symbols`, deleting and rewriting that company's rows), DDL in
`pilot3/schema.py` (`rating_event`, `concentration`, `related_party_txn`, indexes `ix_re/ix_conc/ix_rpt`), and the
three names are in the `pilot3_sql` table list in `plugins/reality-data/server/server.py`.

- `rating_event`: agency/instrument/rating/outlook/action from a rating table (`Rating agency` + `Programme` +
  `Ratings assigned`, or `Rating agency` + `Rating` + `Outlook`), the migration cell giving the action (`Nil` =
  reaffirmed); a prose sentence naming one agency and its ratings is the same row; "has not obtained any credit
  rating" is `not_rated`; a rating-linked clause in any filing (coupon step-up on a downgrade, recall right) is
  `trigger` with the clause in `trigger_text`, which is why the reader also reads `announcement` documents.
- `concentration`: bucket (top 5/10/20, single largest) or population (all trading houses, all dealers) x measure
  (share of deposits/advances/exposure/revenue/purchases/liabilities), one row per printed year column read from its
  own header, plus the prose form ("the top 20 depositors comprised of 4.81% of total deposits").
- `related_party_txn`: a related-party note found by wording, its continuation pages followed for up to four pages;
  each row a counterparty (corporate-suffix name or a party heading such as "Remuneration to KMP") with the printed
  heading as `txn_type`, one row per year column, `basis` keeping standalone and consolidated apart.
- `basis` comes from the page's own header (`not_stated` where it prints none); `entity` from `company.name`;
  `known_at` from the document.
- Measured on the `pilot10` copy (`--part notes`, all ten companies, **11.0 s**): 84 `rating_event`, 74
  `concentration`, 722 `related_party_txn` rows; BAJFINANCE p373/p374, INFY p125/p241/p320, ETERNAL p181/p273/p387,
  MARUTI p115, HDFCBANK p415 and KEC p76 all read as the ticket lists them; hand read 15 random rows per table
  against their pages, every sampled row anchored and right after the transaction-word and corporate-suffix guards.
  Known limits (party-category notes with no year pair, a note continuation past four pages, a wrapped entity name)
  are in `docs/PILOT3_BLUEPRINT.md` section 9f. Test: `reality_engine/tests/test_pilot3_note_tables.py`.

### O17. Holiday copy detector for `daily_price_delivery` (T-089, 6 Nov 2026)

`reality_engine/scripts/price_holiday_copies.py` reads the store read-only and lists every stored date whose rows repeat the previous stored date exactly on `open/high/low/close/prev_close/total_volume/num_trades/deliverable_volume`, with date, weekday, row counts, share identical and the NSE-holiday label. 6 Nov 2026 run: 57 dates / 113,195 copy rows (56 non-session dates, 111,535 deletable; 2021-11-04 is the Muhurat session overwritten by the prior file and must be replaced, not deleted); `--apply-plan FILE` writes the (date, symbol) rows a delete would remove and deletes nothing. Copies are written by `nse_client.fetch_bhavcopy` stamping `DATE = target_date` on the fetched file without checking the file's own date, via `pipeline/backfill.py`. Test: `reality_engine/tests/test_price_holiday_copies.py`; evidence and reader impact: `.tmp/T-089_report.md`.

**Fixed 7 Nov 2026 (T-099).** `reality_engine/scripts/price_holiday_fix.py --db ... --plan ... --backup-dir ... [--apply]` re-checks that every plan date is still an exact copy (stops otherwise), backs the whole table up to parquet, deletes the plan rows and replaces 2021-11-04 with the EQ/BE rows of `mkt_nse_full_daily`, then recomputes indicators per 400-symbol chunk (`HistoricalBackfillManager.recalculate_all_technical_indicators(symbols)`, about 1 GB RAM). Run: 111,535 rows deleted, 2021-11-04 now 1,794 NSE rows (INFY close 1,708.7, volume 483,407). The restore exposed one more copy: 2021-11-05 (Diwali holiday, no NSE row) held the real Muhurat data one day late, so its 1,659 rows were deleted too and those symbols recomputed. Re-scan: no holiday copies, 3,081,572 rows. Backup `D:\RealityEngine\backups\T-099\daily_price_delivery_before_T-099.parquet` (3,194,632 rows). Writer guard: `nse_client.fetch_bhavcopy` now refuses a file whose own `DATE1` is not the asked date (a stale cache is quarantined and fetched once more), and `find_recent_trading_days` caches or counts a day only when its file prints that date (`bhavcopy_file_dates`, `bhavcopy_text_date_ok`; test `reality_engine/tests/test_bhavcopy_date_guard.py`).

### O18. Where every document is: `doc_locations.py` (T-101, 7 Nov 2026)

`reality_engine/scripts/doc_locations.py` reads four catalogs (`corporate_documents`, `raw_documents`, `deck_figures.db:deck_sources`, `results_notes.db:docs`) and a full listing of the Drive archive. The listing is made with `rclone lsjson -R --files-only --hash --fast-list gdrive:InfoDiffusion_archive/<folder> > listing_<folder>.json` for `pdfs`, `D_pdfs`, `decks`, `results_pdfs` and `macro_pdfs`: 94,503 files, about 540 GB, listed in 31 s, names and sizes only. It writes `doc_location` (one row per catalog row: `location_kind` disk+drive / disk / drive / not_held / not_held_no_file_ref, `disk_path`, `drive_path`, `drive_matched_by`) and `drive_unlinked` (Drive files no row points to) to `D:\RealityEngine\drive_index\doc_locations.db`. Disk is the stored path, a sha-named file in the raw store, or the same `_<hash8>_<rest>` name under `D:\RealityEngine\pdfs` with a drifted date prefix; Drive is the stored path, the drifted name, or a sha256-named file. A second archive folder of the same name (Drive id `1aSQEfkMMGmpEpDDq7tI9MH7kmNJNemTH`, the 17 Oct browser upload, 33,276 files, 100 GB, visible only through the `gdrive_ro` remote because `gdrive` has `drive.file` scope) is read as `listing_arch17.json` (`rclone lsjson -R --files-only --hash --fast-list gdrive_ro: --drive-root-folder-id <id>`), and a drifted name also matches under another prefix by its last two folders (`hash_suffix_other_folder`). Run 7 Nov over 235,010 rows: disk+drive 54,018, drive 98,960, disk only 346, not_held 13,535 (a path or hash is recorded but no file exists on this machine or Drive), not_held_no_file_ref 68,151 (a link never downloaded: 37,142 other filings, 15,633 announcements, 10,592 annual reports). Drive files linked to no row: 2,822, of them 2,103 in the second archive.

**Moving raw files to Drive (T-102, Shivam 7 Nov: raw files only on Drive).** `reality_engine/scripts/raw_to_drive.py --root ... --listing-dir ... --manifest ... hash compare upload delete [--delete]` hashes every non-database file (md5, Drive's own hash), marks it `on_drive` when any Drive file has the same md5 and size, uploads the rest to `gdrive:InfoDiffusion_archive/msi_raw/<root>/<rel>` with `--checksum`, and deletes a local file only when its md5 and size are on Drive; `--keep <prefix>` (repeatable) is never uploaded or deleted, used for the research library `D:\RealityEngine\raw\user_research`, which stays local by Shivam's ruling.

**Fetch on demand (T-102, 7 Nov 2026).** Once a file is deleted locally, every raw reader goes through `reality_engine/raw_store.py`: `RawStore` loads the manifest (`D:\RealityEngine\drive_index\raw_to_drive.db`, `local_file.root/rel/md5/drive_path`; only rows with a `drive_path`) once and keys it by `(root, rel)`, never by the stored mixed-slash `path`, so a path maps by which configured root it sits under (`raw` -> `RAW_ROOT`, `pdfs` -> `PDFS_LEGACY_DIR`). A reader asks `exists(path)`, `walk(folder)`, `glob(folder, pattern)` or `subdirs(folder)` and sees Drive-only files as if they were on disk. `local(path)` yields the local file, or downloads the Drive copy into a `raw_fetch_*` temp folder, checks the manifest md5 and deletes it when the `with` ends; `prefetch(paths)` fetches a whole company in one `rclone copy --files-from` per Drive top (8 transfers, `--checksum`) and deletes the temp folder once, so a job is one download and one delete. `REALITY_RAW_FETCH=0` turns Drive off for tests and offline runs; rclone comes from `shutil.which("rclone")` (`RCLONE_BIN` overrides). Switched readers: `pilot3/docs_collect.py` (`discover`, `collect`, `collect_manifest`: one `prefetch` per company), `comparatives._open_pdf`, `kpi._pages_docs`/`_doc_sources` (`_pdf_context` holds an open document inside the store's `local`), `pilot3/hp_ocr.py` (`_resolve_pdf`, `write_plan`), `pilot3/ocr.py` (`pending`, `run`) and `plugins/reality-data/server/lookups_docs.py` (`_local_pdf`, `_pdf_page_text`); `doc_identity.resolve_file` answers a file the manifest maps to Drive as `drive` (its remote from the manifest) instead of `not_held`, so the identity scan keeps its bounded 50-file fetch sample (`DRIVE_FETCH_LIMIT`) and never downloads every row. A generator that yields an open PDF keeps its `local` scope open while the consumer reads the pages, because Windows cannot delete a file PyMuPDF still holds. Test `reality_engine/tests/test_raw_store.py` (fake rclone; 9 with `test_raw_to_drive.py`). Step 4's KEC comparison (7 Nov, after the full upload): with two empty roots `docs_collect` built 621 docs / 5,454 pages in 326 s, the same as the real-root run (122 s) doc for doc, page for page and by page-text hash, and left no `raw_fetch_*` folder. Manifest roots the store maps: `raw` (`REALITY_RAW_ROOT`), `pdfs` (`REALITY_PDFS_LEGACY_DIR`) and `sandbox` (`REALITY_SANDBOX_ROOT`, default `D:\RealityEngine\sandbox`, the pilot loop copies `kpi` and `hp_ocr` read); the scratch roots `ocr_large_20261101`, `ocr_test_20261101` and `tmp_notesfix` are archived under `msi_raw/<root>` but no reader maps them. The HP has no rclone: its `C:\RE\{raw,sandbox,ocr_large,jobs}` were hashed there (manifest `hp_raw/hp_manifest.db`, copy in `D:\RealityEngine\drive_index\hp`), compared on the MSI, and the files not already on Drive went up as one tar per root, `gdrive:InfoDiffusion_archive/hp_raw/hp_<root>.tar` (members are `<root>/<rel>`, md5 checked against the local tar), then deleted on the HP; no reader maps them, so restore with `rclone copy` plus `tar -xf`. During testing new fetches may write raw files locally again (Shivam, 7 Nov); sweep them with the same `hash compare upload delete`.

**Drive files other machines uploaded (T-126, 8 Nov 2026).** The manifest listed only this laptop's uploads, so files the MSI, the 17 Oct `arch17` upload, `pdfs/`, `D_pdfs/`, `decks/` and `results_pdfs/` put on Drive were invisible to every `RawStore` reader (the fresh6/hold6 stores stopped at March 2024 although 282 of their 308 FY25-FY27 transcripts, decks and annual reports were on Drive). `python -m reality_engine.scripts.drive_index_unlisted --listing-dir <dir> list index [--dry-run]` lists each Drive top with `rclone lsjson -R --hash` (arch17 through `gdrive_ro:`), writes every file to manifest table `drive_file` (drive_path, size, md5, sha256, drive_id, root, rel), and gives each file no `local_file` row names a row `status='on_drive_unlisted'`, `path='drive:<drive path>'`, mapped by `MAP` (`pdfs/`, `D_pdfs/`, `msi_raw/pdfs/`, `arch17/.../pdfs/` -> root `pdfs`; `msi_raw/raw/` -> `raw`; `decks/`, `results_pdfs/` -> `raw/decks/`, `raw/results_pdfs/`); a (root, rel) already served is left alone, and the manifest is backed up first. 8 Nov run: 186,751 Drive files, 85,933 unlisted, 79,421 added, 6,160 same path, 352 unmapped (`hp_raw` tars and other tops). A Drive file the manifest already names can still lack its own path: T-102 matched any Drive copy by md5, so `pdfs/ANANDRATHI/CONCALL_TRANSCRIPT/f.pdf` was recorded only as the Drive copy of `raw/concall_pdfs/<sha>.pdf`, and a reader asking for `D:/RealityEngine/pdfs/ANANDRATHI/...` found nothing (130 of the 170 q12 rows). Every listed file now gets a row for its own mapped (root, rel) unless that key is served; second run added 43,411. `drive_file.sha256` lets a reader find a file by the hash `corporate_documents.sha256_hash` records. Re-run after any other machine uploads. Test `reality_engine/tests/test_drive_index_unlisted.py`. A profile build reads only its own raw `manifest.csv` (`collect_manifest`), so a newer document needs a manifest row too: `collect_manifest` now builds its store from the default roots plus the profile's raw root, so a row may name a file under the old D: PDF pile (`D:/RealityEngine/pdfs/<SYM>/<TYPE>/<file>`) that only Drive holds. 8 Nov q12 build (fresh6 + hold6 companies): 170 FY25-FY27 transcripts, decks and annual reports from `corporate_documents`, matched to Drive by `drive_file.sha256` then file name, were added as rows (`source='corporate_documents'`, bucket from the doc type).

**Shivam's ticket board (8 Nov 2026).** `reality_engine/scripts/ticket_board_report.py` writes `D:\RealityEngine\reports\ticket_board.xlsx` (summary + one sheet per group: Open, In progress, Pending a bottleneck = WAITING/LOOKING, Closed (resolved) = DONE or DROPPED as merged/done/fixed/built, Sidelined = other DROPPED) and the same `ticket_board.html`, from `tasks/TASKS.md` + `tasks/TASKS_DONE.md`. It is Shivam's source of truth, so it is rewritten after every `task_board` add/set/done/drop and by the `post-commit` hook (installed by `doc_gate.py --install`) when a commit on main touches `tasks/TASKS*`. One-way sync; a file open in Excel is reported and retried at the next sync. `REALITY_TICKET_BOARD_SYNC=0` turns it off; `REALITY_REPORTS_DIR` moves it. Test `reality_engine/tests/test_ticket_board_report.py`. Shivam retired the 3-7 Nov reports on 8 Nov (answer checks, model-vs-store, dig, second read, re-ask, embedding, OCR, night-loop, doc-identity scans, database inventory): they are no longer in `D:\RealityEngine\reports`; copies are on `gdrive:InfoDiffusion_archive/reports/retired_2026-11-08/` under the same names.

**Session-start budget (8 Nov 2026).** `load_context.py` reserves the ticket card and the `More state` footer before adding optional STATE sections, and adds the decision-log headings last, only while under `LIMIT` (9,800; Claude Code cuts hook output at 10,000). The rulings and STATE's `Now` / `Next action` always print whole. The two caps (RULINGS 8,000 + STATE 4,000) exceed the hook budget together, so keep the pair under ~9,000 in practice (8 Nov: 6,943 + 2,363).

**Standing-rules sheet (Shivam, 8 Nov 2026).** `reality_engine/scripts/standing_rules_report.py` writes `D:\RealityEngine\reports\standing_rules.xlsx` (+ `.html`): every ruling in `tasks/RULINGS.md` with how it reaches each session: session-start prompt (`load_context.py`), MCP `project_rules`, the dsh context pack, the code gate that refuses the action (`[check: ...]` tags via `CODE_GATES`, untagged ones via `CODE_EXTRA` regexes) and the Claude memory files sharing its words (keyword score >= 0.25); sheet Mechanisms says where each lives, whom it reaches and whether it is enforced. The post-commit hook rewrites it when a main commit touches `tasks/RULINGS.md`; `python -m reality_engine.scripts.ruling add ...` rewrites it in the same command that appends a new ruling (T-127). Test `reality_engine/tests/test_standing_rules_report.py`.

**Per-run answer report (Shivam, 8 Nov 2026).** Every question/answer run ends with `python -m reality_engine.scripts.answer_run_report --run <graded.jsonl> --name <topic>`: `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.xlsx` (sheets Summary, Answers, Errors, Documents, Root causes, Wishlist) and `..._answers.csv`. One JSONL object per question: run_id, qid, symbol, question, reframed_question, as_of, use, kind, tools, answer, sources [{doc_key, doc_type, page, known_at}], grade (right/partly/wrong/not_held/scope_out), error, root_cause (raw_missing, not_extracted, wrong_row, quarantined, routing, reading, compute, question), fix, source_if_missing; an unknown grade or root cause is refused. Test `reality_engine/tests/test_answer_run_report.py`.

**Asking a test store from the shell (T-124, 8 Nov 2026).** The reality-data MCP serves one pilot3 database per server start. `python -m reality_engine.scripts.p3ask --db <file.db> <tool> key=value ...` runs the same `lookups_pilot3` (kpi, fin, ratio, holding, statements, guidance, docs, search, sql), `lookups_semantic` (`semantic`), `lookups_tech` (`tech`), `lookups_ratings` (`ratings`, which reads the outside-doc rating store named by `REALITY_RATINGS_DB` instead of `--db`, T-139) and `calc` code against any build, values parsed as JSON where they parse, reply printed as JSON; errors come back as data like the MCP's `_safe`. `catalog` (T-135, `plugins/reality-data/server/calc_catalog.py`, `name=list` lists the ids) runs the named formulas. Used so a subagent with only a shell can answer questions on a hold-out store (q12) exactly as a model on the MCP would. Tests `reality_engine/tests/test_p3ask.py` and `reality_engine/tests/test_calc_catalog.py`.

**7 Nov 2026 clean-up (Shivam).** Deleted, not uploaded: the old pilot designs `reality_engine/data/pilot/pilot60/`, `reality_engine/data/pilot/v4/`, `D:\RealityEngine\pilot\`, the deck-chunk store `chunks_v2` and their backups under `D:\RealityEngine\backups` (20.4 GB; list in `D:\RealityEngine\drive_index\deleted_old_pilot_designs_2026-11-07.json`). The live reality-data server never read them; the old `reality_engine/pilot/*` and `reality_engine/query/*` code and their tests still name them and will fail if run. Moved to Drive with `rclone move --checksum` (same folder names under `gdrive:InfoDiffusion_archive/`): the stale vector indexes `vector_index`, `vector_index_nemotron8b`, `vector_index_qwen8b`, `vector_index_qwen8b_ar`, `lancedb`, and the server's `.cache` (to `reality_data_cache`), so dense search in `search_docs` reports unavailable until a re-embed after the schema is final. `concall_facts.db` stays: the server's `facts()` tool reads it. Manifest `D:\RealityEngine\drive_index\raw_to_drive.db` (`local_file`: path, md5, status, drive_path, deleted_at) is the map from an old local path to its Drive copy. Test `reality_engine/tests/test_raw_to_drive.py`. Not covered yet: raw-store folders with no catalog (`D:\RealityEngine\raw\material_announcement`, `nse_announcements` and others), and the HP laptop. Test: `reality_engine/tests/test_doc_locations.py`.

**Model-read rows withheld (T-103).** `plugins/reality-data/server/core.py` labels every `facts()` row `extraction=filed_xbrl` or `extraction=model_read` (the latter also `verified=false`); the three model-read stores `ar_facts`, `deck_figures` and `concall_facts` were extracted by AI models in October 2026 and never hand-verified, so a default answer withholds them and counts them in `model_read_withheld`, returning them only with `include_model_read=true` or an explicit `kind` of `ar`/`deck`/`concall`. Filed `results_xbrl` ranks first: source rank 0 in `_fact_rank` (was 1) and `results` leads the financials/segments interleave. `search_docs()` drops its `ar_facts` annual-report leg unless `include_model_read=true`, then labels those hits `extraction=model_read`. Tests: `plugins/reality-data/tests/test_reality_data.py` (`test_facts_withholds_model_read_rows_by_default`, `test_facts_include_model_read_labels_and_ranks_xbrl_first`, `test_facts_explicit_ar_kind_keeps_model_read_rows`) and `plugins/reality-data/tests/test_search_docs.py` (`test_model_read_quotes_withheld_unless_requested`).

### O19. Research prototypes: which held facts move forward returns (T-118, 8 Nov 2026)

`reality_engine/research/factor_weights.py` (tests `reality_engine/tests/test_factor_weights.py`, 22
passed) builds a monthly point-in-time panel from the dated DuckDB snapshot, 2021-01 to 2026-10,
93,057 company-months over 2,266 companies, and ranks 35 held facts by forward 6/12/24-month total
return over the Nifty 500 TRI: rank IC with Newey-West t-stats, quintile spread, size terciles,
period split, a Fama-MacBeth joint model, sector re-rating and the 12-month price-move split by
sector. `python -m reality_engine.research.factor_weights --out .tmp/t118` (~110 s, read-only
snapshot, DuckDB memory_limit 5 GB) writes `factor_ic.csv`, `fama_macbeth.csv`, `sector_split.csv`,
`coverage_by_year.csv` and `T-118_factor_weights.html` there. Method, the PIT rule, coverage per
year, the ranked factors per horizon and the store limits it found (2019 quarterly filings, the 2022
shareholding backfill): `docs/research/T-118_factor_weights.md`.

### O20. v2 period engine (T-134, 9 Nov 2026)

`reality_engine/v2/periods.py` gives every v2 value an exact start/end (`period_row`, `fiscal_label`: Q2FY27,
H1FY27, 9MFY27, FY26, H2FY26, TTM to Q2FY27, a POINT day; March year end, `fy_end_month=12` for a December
company) and stores derived quarters, H2, TTM, YoY and QoQ as `fact` rows of kind `derived` with a `derivation`
row naming the formula and the input fact ids, so the answering model never subtracts or sums. `derive()` refuses a
period with conflicting current facts, never overwrites a reported figure (it writes `derived X vs reported Y` on
its `check_detail` instead), and `as_of` replays the facts known at a date. Rules, formula ids and the growth
definition convention are in `docs/V2_SCHEMA_CONTRACT.md` section 9; tests are
`reality_engine/tests/test_v2_periods.py`; the read-only store report is
`python -m reality_engine.v2.period_report --db <pilot3 store> [--symbol SYMBOL]`.

### O21. Rating rationales (T-139, 9 Nov 2026)

`python -m reality_engine.ingestion.rating_rationale_client --store D:/RealityEngine/p20/p20new.db --out .tmp/ratings_p20 [--since 2024-04-01] [--symbols HAVELLS,TITAN] [--max-per-agency 4]` fetches the public rating-rationale text for every company in the store. It stores text only (never the PDF/HTML): `<out>/<SYMBOL>/<AGENCY>_<YYYY-MM-DD>_<id>.txt` plus `<out>/index.csv` (symbol, agency, rating_date, url, instrument, rating, outlook, action, chars, sha256, fetched_at). A URL already in the index is skipped, so a rerun resumes; at most the latest 4 per company+agency since `--since`; one request/second/host with a browser User-Agent and backoff on 429/5xx. Tests: `reality_engine/tests/test_rating_rationale.py` (8 passed, no network).

`python -m reality_engine.ingestion.rating_rationale_load --src D:/RealityEngine/outside_doc/ratings_p20 --out .tmp/ratings.db` is step 2: it loads those texts into one small SQLite file that the `pilot3_ratings` MCP tool and `p3ask ratings` serve (the controller copies it to `D:/RealityEngine/outside_doc/ratings.db`; `REALITY_RATINGS_DB` names another build). Table `outside_doc` is exactly the `reality_engine/v2/schema_v2.sql` DDL (one row per text, the whole text verbatim in `text`); the columns it lacks are side tables: `rating_doc` (symbol, agency, rating_date, known_at, title, url), `rating_action` (instrument, rating, outlook, action, amount_crore, rating_date) and `rating_section` (section, text — verbatim, one row per key). `known_at` is the index `rating_date` and never earlier than the press-release date printed in the head of the text: the later wins. Sections are split on the printed headings (CARE `Rationale and key rating drivers`/`Key strengths`/`Key weaknesses`/`Rating sensitivities`/`Liquidity: Strong`; ICRA `Rationale`/`Key rating drivers and their description`/`Credit strengths`/`Credit challenges`/`Rating sensitivities`/`Liquidity position: Strong`; CRISIL `Detailed Rationale`/`Key Rating Drivers - Strengths|- Weaknesses`/`Rating sensitivity factors`/`Liquidity Superior`/`Outlook`); a wrapper heading with no body of its own is not stored. Instrument rows are read from the summary table above the first rationale heading; a text with no table (a CARE "Credit Update") keeps its `index.csv` row as the one action. Pilot20 run (9 Nov 2026): 41 texts (CARE 21, ICRA 13, CRISIL 7) for 10 companies -> 41 docs, 154 action rows (113 print an amount), 211 sections: every text has at least one action row and 40 of 41 split into sections (the CARE Credit Update has none). `python -m reality_engine.scripts.p3ask --db D:/RealityEngine/p20/p20new.db ratings symbol=HAVELLS as_of=2026-11-08` (with `REALITY_RATINGS_DB=.tmp/ratings.db`) returns the CARE AAA; Stable action with its sections. `plugins/reality-data/server/lookups_ratings.py` `ratings(symbol, as_of=None, agency=None, section=None, limit=20)` is point in time on `known_at`, returns `actions` (agency, rating_date, instrument, rating, outlook, action, amount_crore, known_at, url), `documents` with `sections` verbatim, and `latest_by_agency`; `section=triggers` is an alias for `sensitivities`; a company outside the store returns `found=false` with `available_symbols`. Tests: `python -m pytest -q reality_engine/tests/test_rating_rationale.py plugins/reality-data/tests/test_lookups_ratings.py` (19 passed). u8 + q12 run (9 Nov 2026, 23:59): the client saved 44 texts for 8 u8 companies and 53 for 10 q12 companies (`D:/RealityEngine/outside_doc/ratings_u8`, `ratings_q12`; India Ratings and Acuite still 0); the three folders are merged into `ratings_all` (one `index.csv`) and loaded as the live `ratings.db`: 138 docs, 592 action rows, 674 sections for 28 companies (the p20-only file is kept as `ratings_p20only_2026-11-09.db`). `p3ask --db D:/RealityEngine/u8/u8.db ratings symbol=CHOLAFIN as_of=2026-10-19` returns 6 actions (CARE AA+ Stable sub-debt reaffirmed 2026-08-12, known 2026-08-27).

Listing endpoints found (probed 2026-11-09), also written in the module docstring:
- CARE: `https://www.careratings.com/header/searchlistinsights?cinput=<name>` returns JSON (`CompanyName`, `CommonContent[].PDf`); PDF at `https://www.careratings.com/upload/CompanyFiles/PR/<PDf>`.
- CRISIL: `https://www.crisilratings.com/bin/crisil/listing/rating_sme_listing_service.json?cmd=RR&start=<n>&limit=<end>` returns JSON with one current release per rated entity (39,819 rows); `limit` is an end offset, not a page size. Doc: `https://www.crisil.com/mnt/winshare/Ratings/RatingList/RatingDocs/<ratingFileName>`.
- ICRA: `https://www.icra.in/Rating/AllRatingRationales?Keyword=<name>` returns HTML rows (date, title, Id); PDF at `https://www.icra.in/Rating/ShowRationalReportFilePdfViewer/<id>`.
- India Ratings: `https://www.indiaratings.co.in/home/GetSearchIssuerData_PressRelease_Research?searchKey=<name>&noOfShowEntry=20` returns JSON, but `/pressrelease/<id>` is an Angular shell that did not serve text on 9 Nov 2026, so nothing is saved yet.
- Acuite: `https://connect.acuite.in/liveratings?page=1` lists live ratings, but its company-search POST answers 405 and no pilot20 company is Acuite-rated.
- Brickwork: `PressRelease.aspx` is ASP.NET WebForms (`__VIEWSTATE` + `CompanytxtSearch` + `btnSearch` POST); no pilot20 company is Brickwork-rated, so it is not wired yet.
- Moody's and S&P need a login: their action is read from the exchange announcement and never fetched.

Pilot20 run (9 Nov 2026, `--since 2024-04-01`): 41 text files, 1.2 MB, all 10 companies covered — CARE 21, ICRA 13, CRISIL 7 (HDFCAMC by ICRA; Apollo Tyres, Asian Paints and Pidilite by CRISIL). The exchange rating announcements remain the source for Moody's/S&P and for the agency actions themselves.

### O22. v2 table store (T-132, 9 Nov 2026)

`reality_engine/v2/table_cells.py` reads the text layer of a deck or results page into `table_cell` rows (no model,
no OCR, no `pymupdf.find_tables`): rows from word y-centres, a table block from rows with two or more aligned
numbers, column anchors from the numbers' right edges, a header stack from the rows above the block (inside the
table's x-range, stopping at slide call-outs and prose, at most five rows, and carried onto a continuation page),
period headings assigned to their column groups, section labels ended by a new numbered row group, split numbers
and bracketed negatives merged, digit grouping checked, the scale read from the header, the line above the table or
the row label, and the period resolved from the column header and the filing date (wrapped dates, `Q1 25-26`,
`FY25-26`, `9M FY27`, `H1 26-27`, `Dec-24`, `Jun-26`, `YTD FY26`). Round 3 adds: a bare date header is the quarter
ending that day in a results P&L and a POINT on a balance-sheet page or a deck; a bare `9M` / `FY` takes its printed
FY range (`9M 25-26`) or the latest period ending before the filing date; a cell with no row label, no header or a
header that names no resolvable period is not stored; a per-share, count, ratio or own-unit row label keeps scale 1
(`unit_text` `inr_per_share` / `count` / `ratio` / `Rs`); a garbled header date (`30.011.2028`) is dropped, never
guessed; an `Inc/Dec` / `YoY` / `Growth` / `bps` column is stored with `period_id` NULL and
`method='text_layer;delta'`; and a label line printed under (or above) a row belongs to that row. Round 4 adds:
every header phrase is placed by x-position, never by order (and a block too short to sample every column takes the
printed date row as its columns), so a date line split onto a second y-row keeps its own column; `Year ended`, its
`Vear Ended` text-layer garble and `twelve months` are FY while only a bare date keeps the quarter rule; a
`Segment Assets` / `Segment Liabilities` / balance-sheet row is a POINT on the column date (or the end of a
`Q1 FY27` header); a per-tonne / per-unit / `ARPU` / `ARR` / `RevPAR` / `realisation` row keeps scale 1 and `Rs`; a
measure group row (`REVENUE | EBITDA | EBITDA MARGIN`) enters `col_header` as `measure=<text>`; and a garbled label
(`St`, `-------`, `CT2, Yes 529.40`) is not stored. Round 5 adds: `Six months` / `6 months` / `Half year` over a
date column is H1; a label's own currency and the scale word beside it beat the page unit (`ARPU US$` is USD scale 1,
`(US$ Mn)` USD million, `Revenue in ₹ Cr` Rs crore); a bare `as a % of NR` / `% of revenue` / `margin %` row under a
line item takes that item as its parent; a tall label joins the numbers sharing its top edge (the Coal India
`MCL ... CMPDIL` rows) and a canonical Roman numeral is a row number while `CIL` is a name; over 30% of a label's
letters in non-words keeps the cell and its value with `method='text_layer;garbled'`; a decimal tail cut off by the
text layer (`7,601.5` + `1`, `2,016` + `32`) merges back; and `As > on > 30.06.2025` is a POINT. `reality_engine/v2/build_cells.py` reads a pilot3
store read-only and writes `doc`, `period` and `table_cell` into `<out>/company/<ISIN>.db`, skipping a document whose
sha256 is already there:

```bash
python -m reality_engine.v2.build_cells --store <pilot3.db> --out <dir> [--since 2025-04-01] \
    [--types deck,results] [--symbols A,B]
```

The full 189-document pilot20 run (76 decks + 113 results, into a fresh `--out` directory, round 9 `.tmp/v2r9`)
wrote 77,105 cells in 122.2 s; 95.1% of cells carry a `period_id`, 86.3% a scale and 0.0% no header (round 8:
75,666 / 95.0% / 86.3% / 0.0%; round 7:
75,846 / 95.1% / 85.7% / 0.0%; round 6:
73,833 / 95.1% / 85.1% / 0.0%; round 5: 74,259 / 94.9% / 85.4% / 0.0%; round 4: 74,486 / 94.9% / 81.9% / 0.0%;
round 3: 75,394 / 95.0% / 78.4% / 0.0%; round 2: 88,941 / 64.6% / 71.9% / 6.1%; a cell with no label, no readable
label or no resolvable-period header is not stored). Round 9: deck 14,333 cells (round 7 13,995, round 8 13,540),
results 62,772. Methods: `text_layer` 71,355, `text_layer;garbled` 1,543, `text_layer;delta` 3,738,
`text_layer;junk_suspect` 388, `text_layer;delta;garbled` 73, `text_layer;garbled;junk_suspect` 8. `reality_engine/v2/cell_sample.py` draws the hand-grade
sample (`--store-dir <dir> --n 100 --type deck|results --seed 29 --out <csv>`; columns doc, page, label, header,
period_id, value_text, unit_text, scale, value, method and a 300-character page snippet). Wolf's own round-7 grade of
the first 30 cells of each seed-29 sample (`.tmp/f7_results.csv`, `.tmp/f7_deck.csv`): results 28/30, deck 26/30,
against 26/30 and 24/30 in round 6. Round 7 fixes, in the round-6 grade's class order: a bare `US$` unit cell keeps
its currency (USD, scale 1 on a per-unit row, never the page's Rs); a period header printed once over its measure
columns spreads over the group and the measure row is kept on either side of it (`measure=Revenue > Q1 FY27`); a
label whose box sits inside a tall figure box keeps its own figures (the Coal India ratio table's 2,752 / 3,052); a
header phrase holding two printed dates is split into two headers; a table title is not a column header, a mixed
`3 months ended | 6 months ended | Year ended` row is read as group spans, a block that yields no cell leaves its
rows to the block below and a cash-flow table's columns are ordered by the opening/closing cash cross-check; a `bps`
column is `bps` and `(MMT)` is `MMT`; an `ii)` / `ii,` marker starting mid-label begins its own printed row; and a
repeated sub-header over date columns becomes `dimension=<text>`. Round 8 restores the two rows an earlier round graded right: Coal India results p20's two-column
Key Financial Ratios table (a right-edge `Remarks` word no longer drops the date row, and the first figure
line takes the label printed over it) and Indhotel deck p33's `Less : Share of Non Controlling Interest` -96%
(a two-word `Var. vs FY24` column is no longer taken for a table title). Round 8 also fixes: a balance/level
row (net debt, borrowings, shareholders' equity, market cap, cash level, coverage, AUM) is a POINT at the
column date while a flow stays the column's period, and a page titled '... as of and for the quarter ended'
is not a balance sheet; a one-cell measure section at the left (`1. Segment Revenue`) and a table title
(`Revenue Analysis`) enter `col_header` as `measure=`; the nearest table/segment title above the stack is
the parent of every row; `Q 2` / `H 1` are period words and a short row keeps its printed x-alignment;
`in 000's` is scale 1000, a bare `Bn` on population/coverage is a count, `(400` + `bps)` is -400 bps and a
decimal-free figure at least 50x both column neighbours is `;junk_suspect` with the value NULL; a label up to
6 points above its figures pairs with that row; and a label gluing two ratio names keeps the row printed
second. Round 9 fixes the round-8 grade and replay classes: a FLOW word inside a label (return, turnover, gain,
loss, margin, income, expense, restatement) now beats a balance word (equity, investments, inventory, cash), so
Bharti's ROE, Titan's inventory turnover and the OCI/FX/Restatement rows keep their printed quarter/half/year,
while operating counts (customer base, towers, co-locations) and balance ratios (debt to working capital, current
ratio, book value) are points; `measure=` comes only from header rows over the columns, never from a row label
(`INCOME`, `Revenue from operations`, `1. Segment Revenue`) - the HDFC AMC results p6 keeps all five columns (91
cells, round 8: 46); on a `Key Financial Ratios` page a 30-September column is H1 and a 31-March column FY (Coal
India p20's Net Profit Margin 22% is H1), a remarks column is neither a header nor a parent; group headings name a
RUN of columns split at the midpoint between headings and a sub-header (`Coal | Other Dry | '000 TEUs | MMT`)
refines only its group run, so Adani's p49/p61 year sequences map by position and its p33/p42/p43 port-volume
tables keep 247 cells each with `dimension=` parents and MMT / '000-TEU units; a bullet, letterhead, title fragment
(`th`), remarks column or boxed side figure is no row's parent, `Page 13 of 59` is never a value, and a split
restatement label keeps `Regrouped Employee Benefits Expense`. The replay gate over every row graded right in
r5-r8 (136 rows, matched on doc + page + value) is 136 kept / 0 lost in `.tmp/v2r9/replay.csv`; the seed-37 grades
are ungraded in `.tmp/f9_results.csv` / `.tmp/f9_deck.csv`. Rules a-j, the measured table, the remaining misses and the tests
(`reality_engine/tests/test_v2_table_cells.py`, 85 in the three v2 test files) are in
`docs/V2_SCHEMA_CONTRACT.md` section 10. Merged 10 Nov 09:45 after the independent Opus grade (seed 37 rows 50-79: results 21/30 strict, deck 22/30; replay 136/136 verified by script; grades `D:/RealityEngine/v2/review/T-132_r9_opus_grades.csv`). The round-9 store is kept read-only at `D:/RealityEngine/v2/p20_r9`; every round's samples (f5-f9), `replay_r9.py` and `replay_r9.csv` are in `D:/RealityEngine/v2/review/samples` (the worktrees are removed).

### O25. Embedding bake-off and semantic search (T-154, 9 Nov 2026)

- `tasks/v2/T-154_bakeoff.py` compared local embedders on 139 pilot20 questions over 16,457 pages (results in
  `D:/RealityEngine/p20/t154/run_*.json`): on the 1050 Ti FinModernBERT recall@20 48.9% and bge-m3 43.2% at ~4 pages/s,
  bge-small 30.9% at 38 pages/s. `tasks/v2/T-154_npu_prep.py` fixes input shapes and FP16 so the HP NPU runs bge-small
  (17.6 pages/s, same recall; int8 breaks recall). Shivam stopped further comparisons (9 Nov).
- Production index: Nemotron 8B on DeepInfra via `reality_engine/pilot3/embed_test.py embed` into `<store>/embed/`
  (pilot20: 14,376 + 200 pages, ~$0.48), served by `pilot3_semantic` (`plugins/reality-data/server/lookups_semantic.py`,
  README). Re-ask results: `reports/2026-11-09_t154_p20_semantic_reask.xlsx`; Shivam: semantic stays, alongside the table store.

### O24. v8.1 label dictionary: one metric per printed label, per sector family (T-133, v8.1 10 Nov 2026)

`reality_engine/v2/label_map.py` reads every `table_cell.row_label` of a v2 cells store and the `kpi_series` of the
pilot3 stores, normalises the label, and proposes one metric per `(label, sector_family)` by **whole-label**
matching (T-133 v8). The phrases it matches are the yaml entries in `reality_engine/pilot3/lexicon/` (the
cross-company statement lines are `reality_engine/pilot3/lexicon/common.yaml`; the common financial lines are
`label_map.EXTRA_COMMON`; the hotel measures `ARR`/`Occupancy` are the new `hotels.yaml`): the normalised label must
equal a lexicon phrase whole, so "Operating Free Cash Flow (EBITDA - Capex)" is
`operating_free_cash_flow[basis=ebitda]`, not `capex`. Before matching, OCR spellings already
seen in the cells are repaired through an explicit table (`liabi6ties`/`liabiities` -> `liabilities`, `seoment` ->
`segment`, `lncome` -> `income`), a word OCR split across spaces is rejoined when the concatenation is a known
word (`Total Com pre hensive Income` -> `total comprehensive income`, `Own ers` -> `owners`), and a **known section
name is repaired by edit distance after its spaces are removed** (`segment liabilties`, `segment l iabifties` ->
`segment liabilities`), never by adding spellings; a section printed without its `>` separator
(`Segment Results a) Switchgears` -> `segment results > switchgears`) still owns the member after it. A label
still garbled (a digit/letter swap, or **v8** a share of its words that are OCR damage: a word out of the
lexicon + corpus vocabulary and within edit distance 2 of a word in it) is
`status='rejected'` with `rule='garbled'`, never a proposal; the corpus vocabulary is every word the cells print
in two or more documents (`set_corpus_vocabulary`), so `CRAR (standalone)`, `purchase of treasury shares` and
`optic fibre network r kms` queue instead of being rejected while `iopening balance` and `gpwis mmt` stay rejected.
**v8.1** adds pilot3's `en_vocab.txt` ordinary-English list to that vocabulary, so `revenue from golf course
operations`, `west coast volume mmt share`, `personal care`, `others` and `rail container volume teus` queue; a
token shorter than five letters is not damage on edit distance alone (a three-letter token counts only one edit
from a statement-line word: `lax` for `tax`), the split word `con sumed` rejoins to `consumed`, and the review's
OCR measure forms are repaired (`totalexpenses` -> `total expenses`, `lialrilities` -> `liabilities`,
`jnvesunents` -> `investments`, `lnve.1otmc11ts` -> `investments`, `Divider) el received` -> `dividend received`).
A label with a clean numeric cell in **two
periods of one document** (v7) or in two or more documents is **not** garbled, so `krishnapatnam`, `lighting and
fixtures`, `Order Book - 31 Mar26` and `Real Estate` are proposed, though **v8** a trusted label still has to look
like a word (a token one edit from a dictionary word is damage: `lax` for `tax`); a one-edit typo is repaired
(`Provisiuns` -> `provisions`), a trailing footnote digit is not junk (`ebitdaal1` -> `ebitdaal`), and only a label
whose unmatched bracket ends it (`(Excl.`) is rejected as truncated. **v7 over-rejection:** a label whose only damage is a digit
glued into one token is readable when the rest of it is a dictionary line (`0ther expenses`, `1c1 provisions`,
`total rrabi6ties`, `lec1se liabilities`), so it queues instead of being rejected; the OCR fixer never corrects a
token the dictionary holds (`consumer` stays `consumer`, never `consumed`), and a trailing date is a column
reference, not part of the metric. A `kpi_series` seed is used only when its own label
passes that rule and the lexicon does not disagree (v6: a `total revenue(s)` seed may say either `revenue` or
`total_income`, because the table decides); qualifiers (pre/post tax, incl/excl lease or acceptances, `LFL`, a
`net of tax & NCI` attribution, a definition bracket's basis) go into `dimension`, and an "excluding access charges
and licence fee" list becomes `excl=access_charges,cogs,licence_fee,...` on the base metric (the exclusion changes
the meaning); `pre_tax` on `pbt` and `post_tax` on `pat` are dropped because they restate the metric, while
`return on equity` keeps them. A **member** row is `from_header` with the member as its dimension only with cell
evidence: its own column headers carry `measure=`, it sits under a segment/container parent, or it is a known
entity name; a statement line (a line-item/measure/heading word, or a label used as a section parent in its own
table) is never a member and goes to the queue. **v7 `from_header`:** a parent that names the measure owns its
child (`Share of profit of: > Associate and joint venture`), a child under a cash-flow
movement/adjustment parent is `change_in_*` (or queues), never a member, a one-letter child is a parsing fragment,
`ARR (LFL)`/`Occupancy % (LFL)`/`Cheques, draft on hand` are measures, not members, and a `Total ...` row whose
qualifier is OCR damage is the section total. **v8:** a weak member leaf with no word the vocabulary or the corpus
knows queues instead of becoming `from_header` (`Receivables > Jnvesunents`, `Ddutcd`), while a measure header, an
entity name, a container parent or the two-document evidence still carries a real name (`JVs > AICTPL (CT-3), JV
with MSC`); the parent's own wording decides an attribution row (`... attributable to > Owners oftl1c Parent
Company`), a TCI total that names no owner stays the total, a period note under a measure is the measure (`[b)
Deferred Tax > Period/ Year`), and an OCR-split "profit from segments ..." parent owns its member. **v8.1:** a
reporting-basis word (`conso`, `consol`) is a heading, never a member; an OCR-near measure leaf maps to the measure
(`Receivables > Jnvesunents` is `investments`, `Divider el received` is `dividend_received`, `Trade lialrilities`
queues); `All-India container` (market share) and `Cargo (MMT)` (volume) are measures, not members; `Food and
Beverages Consumed` under `Expenses` is a cost line, not `total_expenses`; a TCI leaf under an OCI parent is
`total_comprehensive_income_attributable`; and one OCR-merged Other-Equity+EPS row queues (the EPS guard reads `EPS`
in any case). A **measure parent** (`Revenue in`, `Segment Sales`, `Segment Results`,
`Profit from segments`) owns
its child as a member (`revenue in > logistics` is `segment_revenue[logistics]`), while a leaf that is itself a
common metric (CWIP, basic/diluted EPS) keeps its own line over the section and over `from_header`. The cell's
`section > label` parent separates the lines printed in two statements ("interest received" in the cash flow vs
the P&L, profit/non-controlling-interest attribution, "owners of the parent" vs equity); a bare ratio row ("as a
% of NR") carries the line above it in the dimension (`base=contribution` / `base=a_and_p_spend` /
`base=other_sga`); a generated `_pct` name comes from the base metric already mapped for the leaf, never a slug of
the raw text, and a parent's metric is not applied to a leaf that names a metric of a different kind. A key that
carries two meanings (the OCR "items not to be reclassified" section holding both profit and OCI attributable)
queues with no metric. **v6 flow/stock:** a cash-flow "Adjustments for increase/decrease in operating
assets/liabilities" row is `change_in_trade_receivables`/`change_in_trade_payables`/`changes_in_inventories`,
never the balance-sheet stock id; a P&L `Attributable to` parent routes NCI/owners to `profit_attributable`, an
OCI parent to `other_comprehensive_income`, a total-comprehensive parent to
`total_comprehensive_income_attributable` with `attribution=`, and only `Equity > Non-controlling interests` is
the stock `non_controlling_interest`; the parent is part of the key. Junk and heading labels
(`Particulars`, `Less`, `otal`), a sentence fragment ending in an auxiliary verb ("The Parent Company has"), a
one-edit OCR heading (`Particulats`) and a heading row whose cells are all dash/blank (`Current assets` with only
"-" at Apollo) are `status='rejected'` with `rule='heading'`; the same `Current assets` label with numbers stays
the table's total, so the rejection is per family. `unit_kind` comes from `metric_def` when the lexicon states it
(`pcr_stage3` pct, `production_kt`/`volume` tonnes, `employees` count), else from the metric's own quantity word
(`population_covered` count, `total_gbs_on_network` data, `debtors_turnover` x), else from the majority unit of
**that label's numeric** cells (`%` -> pct, `count` -> count, `kt`/`tonne` -> tonnes, `x`/`days`, `MW`/`GW` ->
power, currency -> money); only a currency unit gives money, an unknown or tied unit is NULL, a `from_header` row
is NULL because its header carries the measure and unit (a member with 20-26% margin cells is not a money row), a
currency line (`Unallocable Expenses`) keeps money, and a money figure's currency still comes from the cell, never
the map. **v8:** the label's own unit word wins over the definition (`(Excl. Other Qty.(In Mill. Te)` ->
`volume` tonnes, `Total Minutes on Network` -> count, `Current Ratio` -> x; `Proposal.unit_kind`), and a sales row
printed in tonnes is `sales_volume`, not money. `revenue` is the one canonical revenue id (`revenue_from_operations` is a synonym), `net profit before
tax` is `pbt`, the pre-tax `cash generated from operations` is separate from the post-tax `net cash ... operating
activities` (`cash_flow_from_operations`), `total income` is `total_income`, a printed `net cash` is its own
`net_cash` (the sign is the printed one; never negative `net_debt`), and a bare `working capital` is the
`working_capital` balance, not the days KPI. **v6/v7 table total:**
`total revenue(s)` is table-dependent - `total_income` only when the same table's `revenue` + `other_income`
cells add up to the total (IHCL 2,425 + 62 = 2,487), otherwise `revenue` (Bharti's "Total revenues" 494,626 Rs mn
is the segment-revenue sum); percent columns are not proof, the family row carries the proven answer, and each
cell carries its own table's answer. A unit suffix is never stripped into a broader metric (`EBITDA/ton` and
`EBITDA/tonne $/tonne` stay `ebitda_per_tonne`, `CASA %` is `casa_ratio`). A raw `%` label is a margin, never the money line: `PBT %` is `pbt_margin`, `EBIT %` is
`ebit_margin`, with `unit_kind='pct'` and the suffix kept in the key. `Others` stays a dimension member and only
the segment total is at the empty dimension; a split-header leaf ("before finance costs and taxes") is the total; a
child that names a statement total (`total comprehensive income ...`, `total liabilities`) is routed by its own
wording; and a quantity row or a sub-line under "comprising of" queues instead of `from_header`. **The live
extraction path of `reality_engine/pilot3/kpi.py` stays on `label_matches` + `_own_row_hits` (v7), but v8 corrects
v7's claim that the lexicon edits do not reach it:** `label_matches` reads every yaml, so v8's exclusions sit in the
label pattern itself (`net cash(?! ... generated|from|used|operating|...)`, `\barr\b`, a `margin` lookbehind on
`revenue from operations?`, the anchored `working capital`/`total equity and liabilities` lines, the
`dividend income` / `dividend received` split); `_own_row_hits` drops a shorter hit that starts where a longer whole
label starts, so the per-tower and S&M rows replace the junk `revenue` row. **v8.1** makes a `section > leaf` row the
leaf's row (`_own_row_hits(hit, label)`): a leaf hit must start the leaf (a numbering mark or a filler word such as
`Total` may precede it), a leaf that is another line owns the value (`Dividend income > Finance costs` is
`finance_cost`), and the section phrase survives only before a member leaf (`Segment Liabilities > APMEA`) or a
bracketed note leaf, so the 23 `Dividend income > <line>` cells and the `As a % of Total revenues > EBITDA` margin
rows no longer store the section's money metric. The gate is `D:/RealityEngine/v2/review/label_map_v81/live_kpi_ab.py`: the live matcher
over the distinct `table_v1` labels of the five stores (22,005 rows) and the p20_r4 cells (59,326 numeric cells),
`main`'s lexicon vs the branch's and v8 vs v8.1, every metric moving more than 10 rows or cells right-added or
junk-removed; output `D:/RealityEngine/v2/review/label_map_v81/live_kpi_ab.md` passes (rule 10 of the schema contract). The v8.1
ledger: the lexicon adds 36 right `net_debt_to_ebitda` stored rows (SRF's `Net Debt to EBIDTA`) and nothing else;
against v8 the leaf rule adds 298 right `operating_free_cash_flow` cells (the OFCF lines v8 stored as `capex`) and
removes 23 `dividend_income` junk cells, 4 `total_income` junk cells, 177 EBITDA-margin cells (`As a % of Total
revenues > EBITDA`), 124 PAT-margin cells and 15 `revenue` cells (4 of them right, `Revenue in Rs Cr > Total` -
under 10); no stored row is lost. The whole-label
rule (`row_label_hits`/`label_text`) remains the **dry-run diagnostic** the label map measures (`seed_changes.csv`,
`D:/RealityEngine/v2/review/label_map_v81/seed_changes.csv`), not what the live build stores. The company family comes from the same
`company_industry` ->
`sector_map.yaml` path as `make_profile`. It writes `label_map.db` (`label_map` + `metric_def`, every row
`status='queue'` or `'rejected'`), `review_<family>.csv` (with `rule`, `confidence` and `status`), `coverage.txt`,
`rejected_seeds.csv`, `seed_changes.csv` (the read-only dry run of the new rule over the `table_v1` `kpi_series`
rows), `sample_seed61.csv` (200 proposed rows, seed 61, ungraded, for Opus) and `rejected_seed61.csv` (40 labels
that stay rejected, seeded, ungraded); `--replay <grade.csv>` (repeatable) also writes the grade replay:

```bash
python -m reality_engine.v2.label_map --cells-dir <v2 store dir> \
    --kpi-db <pilot3 db> [--kpi-db <pilot3 db> ...] --out <dir>
```

`metric_def` says whether a metric is a `flow` (the only additive kind), `stock`, `ratio`, `per_share`, `count` or
`price`, so the period engine sums only flows. The sector map carries 27 families and all 63 company rows of
`pilot10`, `p20`, `u8` and `q12` have one; 56 of the 191 basic industries stay `unknown` and no pilot company uses
any of them (the five-store build also reads `n10`, whose `BALRAMCHIN` and `ICICIGI` rows still come out `unknown`).
The v8.1 build on `D:/RealityEngine/v2/p20_r4` and the five `kpi_series` stores proposed 2,020 mappings
(rule 1 match 709, seed 485, member 231, qualifier 30, context 541, table total 22, label unit 2) and 236 metric
definitions (the new `net_revenue`, Bharti's net-of-access line); 71.2% of the 59,326 numeric table rows map to a
metric, 617 rows are rejected as junk/heading/garbled (290 rejected labels, 57 garbled over 105 cells; v8: 42,341
mapped / 71.4%, 882 rejected cells and 431 labels, 197 garbled over 397 cells - the English-vocabulary rule removes
332 rejections), and 99.7%
of the rows are mapped or queued. `ports_logistics` is the only family below the 60% per-family line (59.2%, v8
60.1%); the stop rule (below 60% **overall** coverage) was not hit. The v8.1 seed dry run (sector-aware: each row's
company row is resolved to its family exactly as the build does) changes 3,230 of 22,005 `table_v1` rows in 34
pairs; the live A/B is `D:/RealityEngine/v2/review/label_map_v81/live_kpi_ab.md` (below).
Opus's grades replay with the v8.1 rule and **zero lost right rows over six files**: seed-31 139/139, seed-37
170/170, seed-41 177/177, seed-43 180/180, seed-47 181/181 and seed-53 184/184, with 32/13/4/5/8/9 wrong rows
changed, 9/12/14/12/6/6 unchanged and 20/5/5/3/5/1 still unmapped (a wrong row that stays NULL is not counted as
fixed). The right rows whose answer changed but stayed right and every changed wrong row with its reason are in
the per-row CSVs `grade_replay_seed31.csv` ... `grade_replay_seed53.csv` in `D:/RealityEngine/v2/review/label_map_v81`.
Tests: `python -m pytest -q reality_engine/tests/test_v2_label_map.py` (73 passed, one per v8.1 step included) and
the `row_label_hits` cases in `reality_engine/tests/test_pilot3_kpi.py` (108 passed, 6 errors only because
pytest's `tmp_path` is denied in this dsh sandbox). The measured table, every rule and the
output columns are in `docs/V2_SCHEMA_CONTRACT.md` section 11.

## 3. Ticket tracker

One board for the sessions and the workers (a worker's brief carries only its own row):
`tasks/TASKS.md` (open rows, one per line, kept in its section) and `tasks/TASKS_DONE.md` (closed
rows). The id is the maximum across both files plus one, allocated under the `.tmp/task_board.lock`
file lock.

```bash
python -m reality_engine.scripts.task_board card        # <= 600 characters; load_context.py prints it
python -m reality_engine.scripts.task_board list [--section Data] [--status DOING]
python -m reality_engine.scripts.task_board add --section Data --title "..." --accept "python -m pytest ... -q"
python -m reality_engine.scripts.task_board set T-014 DOING Wolf
python -m reality_engine.scripts.task_board done T-014  # runs `accept:`; a failure keeps the row open
python -m reality_engine.scripts.task_board drop T-014 "reason"
python -m reality_engine.scripts.task_board export tasks.xlsx
python -m reality_engine.scripts.task_board lint
```

`done` runs the row's `accept:` command (with a timeout; the last 20 lines are printed on failure)
and moves the row to `TASKS_DONE.md` with HEAD's short hash; an `accept: Shivam` row needs
`done <id> --shivam`. `lint` reports malformed rows, an id in both files, a DONE/DROPPED row in the
live file, a done row with no commit hash and a dropped row with no reason.

Permissions (`.claude/settings.json`, Shivam 9 Nov 2026): Claude asks only before deleting `tasks/STATE.md`,
`tasks/TASKS.md` or `tasks/TASKS_DONE.md`; editing them is fine, and worktrees, branches and other files are Claude's call.
`done <id> --shivam` no longer prompts. Read denies (`.tmp/`, `plugins/dsh-worker/runtime/`, `tasks/archive/`,
`D:/Shivam_Private`) stay.

Two gates enforce it, on `main` only; `python reality_engine/scripts/doc_gate.py --install` writes
both hooks:

- `.git/hooks/pre-commit` lints the board whenever either tracker file is staged, and keeps
  `tasks/TASKS.md` at 150 lines or fewer.
- `.git/hooks/commit-msg` refuses a message whose `T-<digits>` are all absent from both tracker files, or that names none and has no
  `No-ticket: <reason>` line. `merge_worker` puts the brief's ticket into the merge commit; it does
  not close it.

Session start is a hook, not prompt text (T-125). `reality_engine/scripts/load_context.py` prints
`tasks/RULINGS.md` whole and never cuts a ruling. STATE's `## Now` and `## Next action` follow whole;
its other sections, the ticket card and the recent decision headings are added only while the output
stays under the hook's 9,800-character limit, and a dropped section is named by the closing
`More state: project_state() tool or tasks/STATE.md` line. When RULINGS.md is over its
8,000-character budget the hook's first line is `RULINGS.md is N chars over its 8,000 budget: Opus
must shorten it`, and every ruling still prints. `reality_engine/scripts/project_context.py` serves
the same text on demand: the reality-data tools `project_rules(topic=None)` (the section index, or
every bullet containing all of a topic's 3+ letter words, returned whole) and `project_state()` (the
sections above, with `## Now` and `## Next action` whole, plus the ticket card). `doc_gate.py` also
refuses a staged `tasks/STATE.md` over 4,000 characters or `tasks/RULINGS.md` over 8,000
(`CHAR_LIMITS`, rule `start_files`): 40 STATE lines were still 33.6k characters.

**Worker-branch and test gates (T-127, 8 Nov 2026).** `doc_gate.check()` gained the keywords
`merge_branch` and `added` (the staged diff); `main()` fills them and nothing else needs them.
On a merge into `main`, `dsh_merge_branch()` asks `git rev-parse MERGE_HEAD` then
`git for-each-ref --points-at <sha> refs/heads/dsh`, so a hand merge with `--no-ff --no-commit`
and a custom message is still caught: the merge is refused (gate rule `worker_review`) unless
`tasks/efficiency/worker_reviews.jsonl` has a row whose `id` is that `<job_id>` (the staged copy
when the file is staged, else the working file; a bad JSON line is skipped, an unreadable file
refuses with the reason instead of raising). The same merge is refused (gate rule `merge_tests`)
when staged `.py` files outside `tests/`, `reality_engine/tests/` and `plugins/*/tests/` change
and the staged diff adds a top-level `def` while no test file is staged; a pure fix adds none.
Both are logged to the rule ledger under their gate names. Tests:
`reality_engine/tests/test_doc_gate.py`.

**Ruling intake (T-127).** `python -m reality_engine.scripts.ruling add --section "<section>"
--text "<rule>" [--check "<gate tag>"] [--ticket-title "<gate to build>"]` appends
`- <rule> [check: <tag>]` as the last bullet of that `## ` section of `tasks/RULINGS.md`, refuses
without writing when the file would pass 8,000 characters or 40 lines (printing by how much),
opens a `Workspace` ticket through `task_board.add` when no `--check` is given (`accept:
standing_rules.xlsx shows a code gate for it`, `from: ruling intake`), and rewrites the
standing-rules sheet (a locked xlsx prints a warning, never a failed ruling). `ruling list`
prints the bullet count per section and the characters and lines left. The T-127 gate tags
registered in `standing_rules_report.CODE_GATES` are `worker_review`, `merge_tests` and
`code_worker_limit`. Test `reality_engine/tests/test_ruling.py`.

A worker brief carries `Ticket: T-014` or `No-ticket: <reason>`; a T-number absent from the main
checkout's `tasks/TASKS.md` is refused as `ticket_unknown`, and the brief then carries that one row.
The start gate is `plugins/dsh-worker/server/core.py` (the refusal and the row attached to the
brief) with its field check in `plugins/dsh-worker/server/context_pack.py`, and the tool description
in `plugins/dsh-worker/server/plugin_server.py` states the same field.
`reality_engine/scripts/context_guard.py` (the PostToolUse hook that asked Claude to wrap up at 400,000 tokens)
is unregistered since 9 Nov 2026: Shivam removed the session-length limit; sessions keep done/pending notes in
`tasks/STATE.md` instead.

## 4. Rule and chain-of-command ledger (T-042)

Every gate pass or block is one JSON line in `tasks/efficiency/rule_events.jsonl`
(gitignored, created on demand); `$DSH_RULE_EVENTS` overrides the path.

- `reality_engine/scripts/doc_gate.py` logs one event per pre-commit run on `main` (rule
  `doc_gate`, or `start_files` when a line or character limit is the block) and one per commit-msg run
  (rule `ticket`, carrying the commit's short subject).
- `plugins/dsh-worker/server/core.py` logs every start refusal: `permission_required` and
  `permission_invalid` (`start_gate_permission`), `brief_incomplete` (`start_gate_brief`),
  `ticket_unknown` (`ticket`), `peak_hours` / `peak_hours_imminent` (`start_gate_peak`), and
  `code_worker_limit` (`start_gate_limit`, a third code worker; T-127).

`log_event` never raises into the caller, so a full or unwritable log cannot change a gate's
answer.

Daily report (reads existing records only, no model call):

```bash
python -m reality_engine.scripts.rule_ledger report --since 2026-11-01 --out .tmp/rule_ledger.xlsx
```

Sheets: `Rules` (one row per bullet in `tasks/RULINGS.md`: how enforced, passed, blocked,
sidelined with up to 3 examples, and a state of `enforced`, `followed unenforced`,
`sidelined` or `not measured`); `Workers` (budget parsed from the brief's `Budget:` line,
actual calls from `result.md.events.jsonl`, the worker's own reported counts, over-budget
flags, code-intel calls (history: the column stays for runs before 4 Nov 2026 and is 0 after), outcome, finish-to-merge hours); `Chain of command` (per day,
worker-branch merges against direct commits on `main`, `.py` and other lines, the direct
commits that changed code, and possible `--no-verify` bypasses dated after the log began);
`Efficiency` (the FIX_TRACKER rates from `tool_usage_report.metrics`, not recomputed); and
`Notes` (state and bypass definitions).

A `[check: X]` rule counts as enforced only when X is wired to this ledger (`doc_gate`,
`start gate`, `commit-msg`). `HP work runs headless` names `[check: test_hp_headless]`, which
is `reality_engine/tests/test_hp_headless.py`; it writes no events here, so the report states
`not measured` for it. Every report run re-checks two measured budgets: jobs
`20261101T210210Z-521b20a9` (90 total, 20 before the first edit) and
`20261101T205730Z-172d7dec` (45, 12). Test:
`python -m pytest reality_engine/tests/test_rule_ledger.py reality_engine/tests/test_doc_gate.py -q`.

A unit comes from the table's own note, else `page_unit` (this page, then up to 6 pages back). A rating's `action` is NULL unless the page states one: never assume `reaffirmed`.

Any yaml under `pilot3/lexicon/` is read as a KPI lexicon by `kpi.load_lexicon`, so the note words sit in `pilot3/notes_lexicon.yaml`; a lexicon in that folder with another shape stops the `kpi` and `guidance` parts.

### O16. Document identity before extraction (T-093, 6 Nov 2026)

`reality_engine/pilot3/doc_identity.py` gives every `corporate_documents` row an identity verdict before a page is
extracted: company, fiscal year, type and date, one column and reason each, no model call. Verdicts are `ok`,
`set_aside` (a check failed), `unknown` (fewer than 200 characters in the first five pages: scanned/garbled, never
guessed), `on_drive` (the file is in the Drive archive index and was not downloaded) and `not_held` (neither on disk nor
in the archive index). `doc_identity` rows link to `doc` by `doc_key` = the sha256 (else `corp:<corporate_documents.id>`);
`registry.build_doc` drops a set-aside `doc_key` and `docs_collect.collect(..., set_aside=...)` skips that sha, so a
failure is flagged and left in the store, never deleted.

`resolve_file` tries the stored path through `config.resolve_stored_path`, then a sha-to-path index built once over the
raw store's sha-named folders (`docs_collect.SHA_DIRS`), then the Drive archive index kept by
`reality_engine/toolbelt/drive_fetch.py`. Only a `--fetch-drive` sample (at most 50 files) downloads from Drive; no bulk
download. The company check reuses `ar_wrong_company_scan.page_hits`/`alias_tokens`: a first-page miss re-reads the file
for its auditor's-report pages (a late name) and its own ISIN prefix or scrip code (a renamed company). The fiscal year
is the year in the text against the record date (annual reports and results); a 2022 report under a 2026 crawl date
fails. The type is the first-page text: a newspaper clipping, a meeting notice, AGM proceedings or a 1-2 page covering
letter is not an annual report or a transcript, and the text beats the BSE category in both directions (a transcript
under "Investor Presentation" stays a transcript; an annual report filed under "AGM" stays an annual report when its
pages carry the report). Date is `bse_dissem_ts`, then `publication_date`; when `doc_date` equals the crawl date and no
BSE/PIT field backs it the row is `crawl_date` and the real date, if any, is the page-1 letter's.

```bash
python -m reality_engine.pilot3.doc_identity_eval tasks/dsh_tasks/doc_identity_gold.jsonl   # 20 of 20 (was 5 of 20)
python -m pytest reality_engine/tests/test_pilot3_doc_identity.py -q                       # 21 passed
python -m reality_engine.scripts.doc_identity_scan --symbols KEC,INFY --processes 6        # report + CSV; default D:\RealityEngine\reports, use --report-dir .tmp/idreports in a workspace-write sandbox
python -m reality_engine.scripts.doc_identity_scan --sample 2000 --processes 6 --drive none # stratified projection sample
```

`--processes N` runs N shard processes that write CSVs the parent merges: this sandbox denies the named pipes
`multiprocessing.Pool` needs. Shards inherit stdout and read their ids from a JSON file; `--sample N --seed S` picks a
random sample stratified by `doc_type` (proportional allocation, weight `stratum_size/n`). The CSV adds `linked_url`
(the first http(s) link on page 1), `duplicate_of` (the lowest id of the same company+sha; the build then reads that
file once, while a hash under two symbols, equity and listed debt, is only counted) and `sample_weight`. Measured 6 Nov
2026:

- all documents of the ten pilot companies (831 rows), warm cache, 6 processes: 107 ok, 25 set_aside, 3 unknown, 78
  on_drive, 618 not_held (481 have no sha256 and 67 no path, so `no_hash`, not a failure), 4.5 s (5.4 s per 1,000).
- 2,000-row stratified sample, seed 20261106, **one process, cold: 32.3 s = 16.2 s per 1,000**; the whole table
  (127,253 rows) at that rate is **0.57 h**. The same 2,000 on **6 processes, cold (disjoint seed 20261107): 43.5 s =
  21.8 s per 1,000 = 0.77 h** — on this 8-core host the cold run is I/O-bound on the D: PDF store and 6 readers are
  slower than one; the warm-cache 6-process rate is 5.4–5.7 s per 1,000 (0.2 h projected), so parallelism only pays
  on a warm cache or a faster disk.
- the sample projects: ok 15,151, set_aside 1,083, unknown 64, on_drive 255 (indexed folders only), not_held
  110,699; 1,065 of 1,999 rows have no hash; of 934 hashed rows 256 are on disk, 4 in an indexed Drive folder, **10
  truly missing** (their folder was listed and has no file) and **664 in folders never listed** (`not_indexed`, not
  missing); the ten-company 39.1% was all "folder listed, file absent".
- cover letters: 13 rows (828 projected), all transcripts, 11 print a link — each is a call with no transcript held.
  The ten companies add 24 (20 transcripts, 4 annual reports), 16 with a link.
- duplicates in the table: 735 same-company sha groups, 790 repeated rows (ANNUAL_REPORT 551, CONCALL_TRANSCRIPT 182,
  INVESTOR_PRESENTATION 52, ANNUAL_REPORT_DEBT_ISSUER 5); 87 hashes sit under two symbols (equity + listed debt).
- Drive: the 9 ten-company folders that do not exist were checked against the other prefix; only
  `D_pdfs/MARUTI/ANNUAL_REPORT` has a file (1) under the alternate prefix, the other 8 exist under neither `pdfs/` nor
  `D_pdfs/`. The 2,000 sample's indexed on-drive files project to 255 files / 1.74 GB (6.8 MB each) / 0.21–0.47 h at
  2.91–6.66 s/file (both 8-transfer batch rates measured); the 42,318 projected `not_indexed` files are the unknown:
  if they are all in the archive, that is ~288 GB and 34–78 h of download, so a whole-table run must first list those
  folders (no download) and then fetch.

Known limits: the whole-file re-read on a first-page mismatch costs the large-file cases; a 1-3 page web-link letter
is set aside (nothing to extract) even though its label may be technically right; the Drive index covers only the
folders listed so far, so `on_drive` is a lower bound and `not_indexed` is not evidence of absence.

### O4. pilot3 precision, growth formulas and local OCR (T-049 E, merged unfinished 3 Nov)

- `reality_engine/pilot3/kpi.py`: generic labels (margin, revenue, ebitda) count only on table rows or sentences that also carry a period and a unit; segment comes from the table's row or column header; a chart value takes its period from the nearest axis label; every row has a confidence tier (table_row > table_chart > sentence > sentence_default) and readers prefer the highest. Lexicons in `reality_engine/pilot3/lexicon/` were tightened to match.
- `reality_engine/pilot3/queries.py`: growth, share and mix are formulas over stored rows, not extracted values: `kpi_value`, `kpi_growth` (YoY/QoQ via `prior_period`), `kpi_share`, `kpi_mix`, `book_to_bill`, `coverage_years`, `kpi_fy_sum`; `ratios.py` and `oracle.py` use them.
- `reality_engine/pilot3/ocr.py`: local RapidOCR (ONNX, CPU or DirectML; no model call, no network) for pages with no text layer, 300 DPI grayscale, into table `ocr_page` with word boxes in PDF points and mean confidence; resumable (`--max-seconds`). Pages come from three sources: `pages.db` `doc_page` rows with method `needs_ocr` (PDF from `doc.source_path`, doc_key kept exactly as `build.py` writes it to `doc_page`), sandbox `doc_text` `needs_ocr` pages of documents pages.db does not hold, and the empty-text pages of the `decks_full` PDFs `deck_figures` cites. A page already stored under a key naming the same document (a sandbox `doc_alias` key, or the `decks_full/<sha>` key) is skipped, so no page is read twice. `--pages-db` (default `D:\RealityEngine\pilot3\pages.db`) chooses that source; `''` disables it. The sandbox sources are skipped when the loop database is not on the machine, so a profile build OCRs from pages.db alone (T-121); `build --part ocr` runs this into `<stem>_ocr.db` inside `all`, before `pages`, and `pages`/`extract` read it automatically. `reality_engine/pilot3/hp_ocr.py` (T-052) re-reads the same page set on the HP with Microsoft TextRecognizer at 300 DPI grayscale: `plan` resolves each page's PDF exactly as `pending()` does (old `history/…` keys mapped through `doc_alias`) and copies only those PDFs, `run` starts the resumable `hp_ocr_pages.py` driver as a hidden session-0 task and waits, `fetch` writes `ocr_textrec.db` with the same `ocr_page` columns plus `low_conf_numbers` and `error` (`method='ocr_textrec'`, word boxes in PDF points), `compare` writes `OCR_COMPARE.html`, `cleanup` removes the package, certificate, tasks and copied PDFs from the HP. A page that will not render at 300 DPI or still fails after two retries keeps an error row. `kpi.py` reads `ocr_page` and marks rows with the row's own method and `ocr_conf`; `registry.py` and `kpi.py` prefer `ocr_textrec` over `ocr_rapid` when several `--ocr-db` hold the same page.
  ```bash
  python -m reality_engine.pilot3.ocr --out D:\RealityEngine\pilot3\ocr\ocr_KEC.db --symbols KEC --max-seconds 36000
  ```
  The run is resumable per `ocr_page` key, so a later run picks up the pages this source adds. The OCR databases are merged into the core db by the `pages` and `extract` parts of `build.py --ocr-db` (O5).
  ```bash
  python -m reality_engine.pilot3.hp_ocr plan
  python -m reality_engine.pilot3.hp_ocr run --fresh
  python -m reality_engine.pilot3.hp_ocr fetch
  python -m reality_engine.pilot3.hp_ocr compare
  python -m reality_engine.pilot3.hp_ocr cleanup
  ```
- **T-052, 3 Nov 2026.** The MSI RapidOCR runs finished 1,452 pages (`ocr_{KEC,BAJFINANCE,HINDALCO}.db`: KEC 110, BAJFINANCE 354, HINDALCO 988) and left one `pages.db` page pending after an "Overly large image" failure. The HP TextRecognizer re-read those 1,453 pages from 242 PDFs (1,013.5 MB) in 754 s (12.6 min) on 3 Nov: 1,429 pages with text and word boxes and 24 error rows (BAJFINANCE 18, HINDALCO 6: 23 `NullReferenceException`, and one HINDALCO page 11520x8064 pt that cannot render at 300 DPI and failed on the MSI too), 486 pages with a number under 0.9 confidence. `ocr_textrec.db` holds a row for every planned page; `OCR_COMPARE.html` has the two-engine table and ten sample disagreements. The 24 error pages (18 BAJFINANCE annual-report pages and 6 HINDALCO pages) have no text. The package, certificate, both tasks and the copied PDFs were removed from the HP after the fetch; the worker did not write `reality_engine/data`.
- **Test:** `reality_engine/tests/test_pilot3_ocr.py` (fixture pages.db, sandbox and OCR dbs and a tiny PDF; `ocr_page` monkeypatched, no real OCR: pages.db keys, alias/decks dedupe, `--pages-db ''`, `doc_page`/FTS fill, `kpi --ocr-db` merge, and the method choice — `ocr_textrec` wins over `ocr_rapid` in either db order, in the registry and in the kpi merge). The file shadows pytest's `tmp_path` with a `.tmp` directory, as `test_pilot3_second_read.py` does: the dsh sandbox denies a file inside the 0700 directory `tempfile.mkdtemp` makes.
- `reality_engine/pilot3/kpi_oracle.py`: the KPI and transcript oracle report (was a `.tmp` script): `python -m reality_engine.pilot3.kpi_oracle --kpi <db> --tr <db> [--detail]`.
- Next: the controller rebuilds `pilot3.db` with the four OCR databases and reruns both oracles; the HP page OCR itself is complete (above).

### O5. pilot3 in one database, served by the reality-data MCP (T-049 F, merged 3 Nov)

- `reality_engine/pilot3/build.py` and `registry.py` load documents and pages from `D:\RealityEngine\pilot3\pages.db` (sandbox pages only where pages.db lacks a document; `doc_alias` maps old sandbox keys) and run the extractors into the same file; the real database is `reality_engine\data\pilot3\pilot3.db` (gitignored, 142 MB on 3 Nov). `schema.py` and `__init__.py` carry the new tables and path. `--ocr-db` may be given once per company OCR database (T-052): the `pages` part writes an `ocr_page` text into its `doc_page` row (the method from the `ocr_page` row, `ocr_textrec` preferred over `ocr_rapid`; `ocr_conf` kept, `doc_alias` used for a sandbox key) before the FTS index is built, so `doc_page_fts` and `pilot3_search` find the OCR text; the `extract` part passes the same databases to `kpi.py --ocr-db`.
  ```bash
  python -m reality_engine.pilot3.build --out reality_engine\data\pilot3\pilot3.db --part all --ocr-db D:\RealityEngine\pilot3\ocr\ocr_KEC.db --ocr-db D:\RealityEngine\pilot3\ocr\ocr_BAJFINANCE.db --ocr-db D:\RealityEngine\pilot3\ocr\ocr_HINDALCO.db --ocr-db D:\RealityEngine\pilot3\ocr\ocr_textrec.db
  ```
- `plugins/reality-data/server/lookups_pilot3.py` (read-only via `connect_ro`, small replies, every row with provenance: table, source document + page or store row, `known_at`; `as_of` drops later and undated rows) backs nine tools registered in `plugins/reality-data/server/server.py`: `pilot3_kpi`, `pilot3_fin`, `pilot3_ratio`, `pilot3_holding`, `pilot3_statements`, `pilot3_docs`, `pilot3_search` (FTS over doc_page), `pilot3_guidance` (the forward targets of O6) and `pilot3_sql` (bounded). The server's instructions route every company in the database's `company` table to them first (T-090: the text and the code name no company list), and a guidance/outlook/target/corridor question to `pilot3_guidance` before the other text tools. **`pilot3_kpi`** orders by the extractor's `conf_rank` descending, then a deck/results/press-release/annual-report row before a transcript row, then dimension total and `known_at`: the first row is now the best source (3 Nov 2026). Its SQL window is 30x the reply size (4 Nov 2026): at 3x, a measure restated in many filings filled the window with its higher-confidence duplicates and the lower-confidence period series never reached the reply (Bajaj's quarterly GNPA, KEC's order intake trend returned only old annual rows). The words an investor uses now resolve to the stored metric names (`_KPI_WORDS`, T-165, 10 Nov 2026: NIM / net interest margin -> `nim_pct`, credit cost / losses and provisions to assets -> `credit_cost_bps`, cost of funds / cost of borrowings -> `cost_of_funds_pct`), and an empty reply separates 'not held' from 'held but quarantined': `held_quarantined` names the periods whose only rows the row check hid and says `include_quarantined=true` shows them (CHOLAFIN Q2FY27 NIM 7.9 is exactly that; the metric name is no longer hidden from the alias search by a quarantine). **`pilot3_holding`** returns every filed category row of the quarter by default (promoter, public, `mutual_funds`, `fpi_total`, insurance, `central_government_or_president_of_india` ...) with `pct` and the `pct_basis` its percentage is printed on, one row per category and quarter, the XBRL parse before the `shp_index` copy, and takes `category` (government / GoI / DIPAM, FPI / FII, MF / mutual fund, promoter, public, retail, DII; a no-match filter returns no row and lists `categories_held`) and `quarters=N` for a multi-quarter path (an SHP filed at a record date inside a quarter is not a trend point; one newer than the last quarter end is kept as the newest filing). The quarter in force is the latest one with an XBRL filing, so a newest quarter holding only its `shp_index` promoter row cannot hide the complete previous quarter (Vodafone Idea's GoI 49%, T-165). It also returns the named holders (top 12 by shares; `all_holders=true` lists every named holder including the `pac_*` disclosures with `pac_name`), the filing's own `promoter_pledge` answer (the three flags, promoter and pledged shares, the printed pledged percentage and an `answer` sentence), the `pct_basis` the printed percentages are on and `quarters_held`/`categories_held` (T-088, 6 Nov 2026). **`pilot3_search`** takes `period` (Q1FY27 / FY26), `date_from`+`date_to` (filing window) and `doc_type`; it fetches the OR and AND FTS candidates (bm25), normalises bm25 inside the OR set (best = 1.0, the rest keep their ratio) and adds +0.20 for a page carrying every query word, +0.35 for a filing inside the window, +0.35 for a page that prints the period and +0.20 for the document type named. The `period` argument is normalised through `norm_period`, so the reply echoes a canonical label (FY27, Q3FY26) and a label can never be prefixed twice; a matching page under a document with no filing date no longer raises `IndexError` in the ranker (it reads the page's `known_at` as well). **`pilot3_statements`** takes `period`, `rank_terms` (the question's own words) and `latest`; `topic` now ranks the tagged statements first instead of filtering (the sentence that answers "what did they say about margins" is often tagged `nim` or `other`), `topic_matched` says whether any returned statement carried the tag, and the order is topic, period, how many of `rank_terms` the statement carries, then newest call and sequence. When no stored statement carries the topic, it searches the calls' own `doc_page` text (bm25, newest call first, the date window and `latest` respected) and returns those rows with `fallback: "doc_page_bm25"` and provenance table `doc_page` (4 Nov 2026). Tests: `plugins/reality-data/tests/test_lookups_pilot3.py` (32 tests: 31 pass, 1 skipped (MCP stdio), 10 Nov after T-165).
- **Tool-surface fixes, 4 Nov 2026 (T-049, graded re-answer; section O8).** `pilot3` is now a catalogued database — `catalog(db='pilot3')`, `schema(table, db='pilot3')` and `sql(db='pilot3')` resolve it (a `DB_SPECS` key the shipped `catalog_cache.json` predates is introspected on first use). `pilot3_fin` defaults to the consolidated statement when `basis` is omitted and labels `basis` on every row. `pilot3_sql` takes `max_chars` (default 400, hard cap 8000) for long page text. `pilot3_ratio` serves the new `opex_to_net_total_income_pct` row.
- **Answer check.** `reality_engine/pilot3/answer_check.py` measures how many of the 300 pilot questions the database answers through one lookup call each. Oracle: the newest `answers` row per qid in `D:\RealityEngine\sandbox\{kec,bajfinance,hindalco}_loop\<sym>.db`; the 251 rows whose status is `answered` passed the loop's checks and are the test set, and the other 49 are still mapped and called (`answered_no_oracle` when rows come back). Mapping is fixed rules, no model: the question text names one measure (alias table, then the store's own names for that symbol and period), the period (a question naming two periods asks for all of them) and the basis; documents, share price (`pilot3_sql` over `price_delivery`), a valuation date, a management statement (a call) or document text (otherwise), an announcement, shareholding (`quarter_end` from the question date) and the oracle's cited table break the ties. A derived question whose answer row cites its inputs asks for the derived name when the store holds it (`revenue_growth_yoy_pct` in `ratio_panel`), else for the cited measure. **Text questions (3 Nov 2026):** the keyword builder drops the company's own words (the symbol already scopes the search) and the ask-words, keeps 3+ letter words and fiscal labels (`FY26`, `Q1FY27`); the search call passes the document type the question names (deck / transcript / annual report), the question's fiscal period and a printed month window ("between July and October 2026", "July to September 2026", "in July 2026" -> `date_from`/`date_to`); a management-statement call passes `rank_terms` from the same words, the first period the question prints (the call it names) and `latest=true` for "in the latest call". The check asks both text tools for `LIMIT` = 50 rows per call (the same page size it already used for the measure tools), so a right page ranked 11th-50th still counts. A "sessions/day after its results" question that prints no date takes the results filing's `known_at` from `pilot3_docs` (only a filing after the named period end and within 75 days counts) and then builds the `price_delivery` query from it. A share-price date the market was shut for (31 March 2025 and 31 March 2026 were holidays) reads the last session on or before that day (`MAX(date) <= day`) and the reply carries `as_traded_on`; a price on each of two dates resolves both. A transcript question whose topic word no `lexicon/topics.yaml` tag contains (`price`, `growth`, `dividend`, `rating`, `volume`) passes it as `terms`, because `pilot3_statements(topic="price")` can never match. Each call points the lookups at `--db` (default `reality_engine\data\pilot3\pilot3.db`, via `REALITY_PILOT3_DB`) and runs `lookups_pilot3` directly, with `as_of` = the question's as_of or 2026-10-19; a question that says "as of <day>" uses that day as its cut-off and asks for the latest row.

  **The answer is graded, not its inputs (T-049 F, 4 Nov 2026).** The loop's `numbers[]` are often the inputs of a derived answer (two revenues for a growth, borrowings and net worth for a gearing, a price and a share count for a market cap) while the lookup returns the computed value, so no cited number matches and 111 of 300 read `mismatch`. For a question whose answer is derived (`derived_op`: the cited row's `method`/`formula` field when the loop writes one, else the question text: growth, CAGR, share, margin, ratio, market cap, difference, sum) the check recomputes the value from the oracle's cited numbers and from what the reply holds -- the ratio it returns, or the inputs it returns -- with the same formula (`derived_values`: growth = 100*(later/earlier-1), a fiscal year's four quarters summed when the rows are quarterly, share/margin = part/whole, ratio = numerator/denominator in the order the question names them, market cap = price x shares, trailing PE = price / the four quarterly EPS) and compares the two values with the loop's own tolerance (`gap_loop.checks`; bps, percent and a 0-1 ratio are the only conversions, no tolerance is widened). `compared_on` says which comparison decided the class (`derived` or `cited`); when the reply supports no derived value at all the cited comparison decides, because there was nothing to grade. A number matches when a returned row's value or quote carries it in the oracle number's period, with `gap_loop.checks`' money / percent / count normalisation plus half a unit of the oracle's last printed decimal; a **stored value** keeps the strict period test, while a number **quoted in a sentence** needs the same period too: `periods_within` (a quarter inside the year asked, "Q1FY27" for "FY27") exists but is not applied, because a grader is never loosened to raise a score (Opus at merge, 3 Nov; a Haiku re-run showed it moved 5 classes, 2 of them to `match`). The classes are `match` (every derived value / every number), `partial` (some of them), `mismatch` (rows, but the values disagree), `empty` (no rows), `answered_no_oracle` (the loop's own answer did not pass its checks; the call returned rows) and `no_tool` (no rule matched the question).
  ```bash
  python -m reality_engine.pilot3.answer_check --db reality_engine\data\pilot3\pilot3.db
  ```
  It writes `D:\RealityEngine\pilot3\ANSWERABILITY.xlsx` (one row per question: qid, company, question, the mapped tool and arguments, `class`, `compared_on`, `cited_class`, the oracle's numbers, the numbers returned, the derived values side by side, provenance = table / document + page / `known_at`; and a summary sheet with the counts per company, per tool and per comparison, and the commonest reasons for `no_tool` / `empty`) and `ANSWERABILITY.html` (stacked bar per company, per-tool table, every question; no external script). `cited_class` keeps the old cited-number comparison on every row, so the change hides nothing.
- **3 Nov 2026 state, text tools raised on the rebuilt database (19:10, RapidOCR text in).** Baseline on that database: 114 `match`, 40 `partial`, 91 `mismatch`, 7 `empty`, 48 `answered_no_oracle` of 300; the text tools were the weakest (`pilot3_search` 12 match / 24 mismatch of 62, `pilot3_statements` 2 / 21 of 34). After the changes above (extractor reading the pilot3 pages, speaker/role patterns, search and statement ranking, keyword builder, price holidays, KPI order): **131 match**, 48 partial, 69 mismatch, 3 empty, 49 answered_no_oracle with strict periods (the worker's 133 / 51 / 64 counted quotes from a quarter inside the year asked); per tool `pilot3_search` 20 match / 10 partial / 12 mismatch (was 12 / 6 / 24), `pilot3_statements` 7 / 8 / 8 (was 2 / 0 / 21), `pilot3_kpi` 39 (was 33), `pilot3_sql` 13 match and no empty (the three 31 March holiday questions now read the last session), `pilot3_fin` 33 and `pilot3_ratio` 18 (unchanged). Per company: KEC 46 match (39), BAJFINANCE 49 (43), HINDALCO 38 (32). The 24 search and 21 statement baseline mismatches: 13 moved to `match`, 9 to `partial`, 23 remain (`right page returned but the number is outside the 420-char snippet`, `right page outside the top 50`, `topic/terms filter`, `absolute-INR results line`); none is absent from every page of the database, so the stop rule did not fire. Earlier baselines: 72 match / 33 partial / 111 mismatch on the pre-derived-grading copy; 99 match with the KPI pages.db fix alone.
- **4 Nov 2026, the five KPI defects of the hand-read grade (T-049).** On a copy of `pilot3.db` rebuilt with `--part kpi` (all four OCR DBs plus `ocr_textrec`) and `--part stores`: **134 `match`**, 48 partial, 67 mismatch, 2 empty, 49 answered_no_oracle — was 131 / 48 / 69 / 3. Six questions moved up (`BAJFINANCE027` AUM split partial→match, `HINDALCO004` empty→match, `HINDALCO052` FY26 cash flow mismatch→match, `HINDALCO096` partial→match, `KEC095` mismatch→match, `KEC097` partial→match) and two moved down (`BAJFINANCE045` match→partial, `KEC028` match→mismatch): both ask for a trend, and the `pilot3_kpi` reply is still filled by a measure's 50 oldest highest-tier table rows before the FY25/FY26 rows now stored (the window is 30x but the reply cap is 50); the store side is right (quarterly GNPA with its Q4 labels, order intake FY26 25,280 / FY25 24,689). Per tool `pilot3_kpi` 41 (was 39), `pilot3_fin` 34 (33). Rows: KEC 7,179 / BAJFINANCE 19,084 / HINDALCO 10,950. `test_pilot3_kpi.py` now collects 40 tests: 34 pass and 6 pre-existing `tmp_path` tests error at fixture setup in this DSH sandbox (pytest's temp root is denied); the tests added across the 4 Nov passes cover each defect, including the day-as-year and period-start rules.
- **4 Nov 2026, the three data defects of the MCP re-answer grade (T-049 review).** Full rebuild on a copy of the live database (`--part all`): **134 `match`** (unchanged), 49 partial (48), 66 mismatch (67), 2 empty, 49 answered_no_oracle; one question changed class, `HINDALCO042` mismatch→partial (`pilot3_kpi`), and no match was lost. The same run changed: `doc` 3 KEC transcript filing dates raised to their call date; `kpi_series` 39,773 → 37,985 rows with zero Q1FY27 rows from documents known before 2026-04-01 (24 before) and zero Q1FY28 / Q3FY28 / Q3FY29 rows; `guidance` 660 → 332 rows with no net-debt-as-interest-cost row and no share-of-supply row. The two empty rows are the same two as before (`HINDALCO024` alumina production, `KEC026` international order-book share — neither is stored). `--part all` also re-read the stores, so `fin_annual_line` lost two HINDALCO `company_stated` `net_debt_to_ebitda` rows (3,213 → 3,211) that the current `statements.py` no longer extracts; no question's class moved on that.
- Test: `reality_engine/tests/test_pilot3_answer_check.py` (25 tests on the fixture pilot3 database and fixture sandbox: one question per class, plus a growth whose oracle cites two revenues while the reply returns the growth %, a share over two cited order books, the `terms` fallback for a topic the tagger never emits, the results-date rule, the 31 March holiday price query, the keyword/date-window builder and the quarter-inside-year text rule). With `plugins/reality-data/tests/test_lookups_pilot3.py` (24 tests, all pass; the MCP stdio one skips only inside a sandbox that blocks child-process pipes) the acceptance command `python -m pytest plugins/reality-data/tests reality_engine/tests -q -k "pilot3 or lookups"` selects the pilot3 and lookup suites (195 tests on 4 Nov 2026). `reality_engine/tests/test_pilot3_kpi.py` has 28 tests (transcript source, composite titles, OCR name slips, call-period forms). The reality-data MCP must be restarted (`/mcp`) for a session to see the nine `pilot3_*` tools.

### O6. pilot3 guidance extractor and `pilot3_guidance` (T-049, 4 Nov 2026)

The MCP-only answer run's hand-read grade found the same hole in 10 of 17 wrong answers: the call or deck text that holds the guidance is in `doc_page`, but `pilot3_statements` / `pilot3_search` did not surface it, so the answerer said "no guidance given". `reality_engine/pilot3/guidance.py` (new; no model, no OCR, no network) closes it with a table of forward targets and a tool that answers them directly.

```bash
python -m reality_engine.pilot3.guidance --out <db> [--symbols KEC,BAJFINANCE,HINDALCO] [--limit-docs N]   # ~7 s on the 3 Nov db
python -m reality_engine.pilot3.guidance --out <db> --sample 40 --seed 7                                   # hand check: N random rows with their sentence
python -m reality_engine.pilot3.build --out <db> --part guidance                                          # in --part all after extract
python -m pytest reality_engine/tests/test_pilot3_guidance.py -q                                          # 32 tests
```

- **Table** `guidance` (DDL in `schema.py`, indexes `ix_gd` on symbol+metric+period and `ix_gd2` on symbol+said_on): `id`, `symbol`, `isin`, `metric`, `target_period`, `low`, `high`, `unit`, `direction` (up/down/flat), `said_on` (the filing date), `doc_key` (the ticket's `doc_id`; the column is named like every other pilot3 table), `page`, `quote` (the exact sentence), `speaker` (a transcript), `known_at`, `known_at_source`, `revision_of`, `extractor_rule`. One row per target per date: a target restated on a later call has its own `said_on` (that is what `revision_of` links), while the BSE/NSE copies and the several pages of one document collapse onto one row — the run key is `(symbol, metric, target_period, low, high, unit, said_on)` and the first document in `known_at` order supplies the page and the earliest knowledge.
- **Input.** The database's own `doc_page` for transcripts, decks, results files and press releases (annual reports and announcements are not read: they are backward-looking and would swamp precision). Transcripts are read through `transcript_statement`, so only management sentences are stored (analysts and the moderator are already excluded), with the tested speaker, role and `call_period`; decks/results/press releases are split into sentences (a bullet marker `▪•❑●` starts a new one) and keep the exact page slice. A sentence over 400 characters is a table or chart blob, not a sentence, and is skipped.
- **A sentence is stored only when it has all four of:** a number (percent range `12% to 15%` / `8-8.5%`, basis-point range, currency range `INR20 crores, INR25 crores` (only next to maybe/around/between/another), single value, or `$250 a ton`; T-105 adds a count range in millions, `60 million to 62 million` / `18 MM to 20 MM`, both numbers carrying the word, unit `mn`); a guidance cue (`guidance|guided|corridor|target|estimate|expect|anticipate|should be|would be|will be|going to|going forward|outlook|talking about`, plus T-105's commitment phrasings: `on track|confident|comfortable|clear … to deliver|achieve|reach|add`, `should deliver`, `we'll lower|raise|cut … to`) in the sentence -- or, for a range only, in the 300 characters before it, which is where the analyst's question ("what is the guidance on revenue, EBITDA and order intake?") sits; a metric word in the sentence or within about 300 characters before / 150 after; and a target period. The number taken is the first numeric candidate after the nearest cue, so "costs went up 5% Q1 to Q4 ... expecting another 5%, 6%" takes the forward pair, not the measurement. A metric word inside the sentence must be within 150 characters before the number (or 40 after, measured from the number's own end since T-105, so "a 25 to 40 basis point improvement … on opex-to-NTI" keeps its metric) -- that is what rejects a chart's tick labels; a metric word only in the question may be further away. A sentence with more than five numbers is a chart axis or a table line, not a sentence, and is skipped (`chart_blob`).
- **A target said in words is a row without a number (T-058, 4 Nov 2026).** Ten real guidance sentences were held in `transcript_statement` with no `guidance` row, because they carry no figure: "we expect high single-digit consolidated top line growth for FY27", "the provision coverage will be in the 70s, mid-70s or higher", "we expect the margins to remain flattish", "full year '27 will be ahead of full year '26". `worded_row()` writes them with `low` and `high` **NULL** — no number is invented, "high single-digit" is never 7% — `unit='pct'`, the direction read from the word (`ahead of` / `better than` / `or higher` → up, `flattish` / `in the guided range` → flat, `WORDED_MOVE` / `WORDED_UP` / `WORDED_DOWN`) and the exact quote. It requires the cue, the metric **named in the sentence itself** (never only in the question: a bare "the guidance of 14% to 15%" is the numeric path's), a magnitude or comparison word, and it refuses a reporting verb, an actual's shape, a hedge, a macro forecast, a sentence that declines to guide (`NO_GUIDANCE`: "we do not give forward guidance"), and a metric not stated in percent. `checkpages` skips a both-NULL row (it proves no page number). Test: `test_a_worded_target_is_a_row_without_an_invented_number`, `test_the_worded_families_and_the_three_sentences_that_must_stay_out`.
- **The metric a sentence does not name (T-058).** A company flagged `lender: true` whose sector is not nbfc/bank/banking (a life insurer) keeps its "margin" as `ebitda_margin`; before, it was mapped to NIM and then refused, so every SBILIFE margin row was lost. A bare "the guidance of 60% CAGR" is `revenue_growth`, while an "EBITDA CAGR" / "profit CAGR" is not (`NON_REVENUE_CAGR`); `provision coverage`, `NOV` / `net order value` and "per day per store" are `other`; "we are saying we will get to" is a cue; `full year '27` names its period (`FULL_YEAR`); "guidance" alone cues `other` (`OTHER_CUE`); and a list of example values ("some 25 basis points, some 100 basis points") is not a target (`EXAMPLE_LIST`). Test: `test_a_cagr_is_the_top_line_and_a_store_kpi_is_other`, `test_an_insurers_margin_stays_a_margin_not_a_nim`.
- **The metric must be the target's subject** (`subject_ok`, T-049 review 4 Nov 2026).  The hand check found a net-debt sentence stored as an interest-cost target and a share of supply as an EBITDA-margin target, both because the metric came from the question and any plausible number from the answer.  Now: (a) a share of a total ("60% of our supply", "25% of turnover", "13% share") is never a margin, a level or a rate, only `other`; (b) a percent change is not a percent level ("a 10% reduction in the interest cost" is not interest cost 10%), and no non-growth metric takes a number the sentence itself calls a growth ("we grow at 15%" is not a 15% margin) -- the growth metrics are the one class where the rate is the target; (c) when the sentence names a metric, the chosen metric must be one of them; (d) when it names none (an answer to "what about the interest cost?"), the sentence must itself be a forward statement, the question before it must name the metric, and the number must not have another subject of its own (net debt, borrowings, order book, turnover, supply, cost, a run rate) on either side.  A past measurement that used to leak (`already at`, `had estimated`, `we did`, `they had`, `run rate`) is now a past marker.
- **Metrics** are the ticket's twelve plus T-105's three, in this priority: `nim`, `credit_cost`, `aum_growth`, `ebitda_per_tonne`, `order_intake`, `project_capital_cost` (a project's whole capital cost, T-056), `project_capital_spent` (the spend so far on it, T-056 review: emitted beside the total with the period the sentence names, never read as a candidate from a sentence pattern, so it can never pass as a year's capex), `capex`, `interest_cost`, `cost_of_production`, `revenue_growth`, `ebitda_margin`, `new_loans` (unit `mn`/`count`), `new_customers` (`mn`/`count`; "adding … customers to the franchise" too), `opex_to_nti` (`pct`/`bps`, "a 25 to 40 basis point improvement … on opex-to-NTI"), `other` (a share or structural statement ranks last whatever text it came from). BAJFINANCE's "margin"/"margins" is its NIM; a credit-cost sentence that only names GNPA/NNPA is asset quality, not credit cost; a number must be plausible for the metric and unit (a 70-75% "margin" is a share of PBT, a 20% interest cost in Brazil is a market rate, a margin above 50% is rejected). A "margin" is mapped to NIM only for a lender whose sector is a bank or NBFC (T-058: an insurer keeps `ebitda_margin`).
- **Periods.** Explicit `QnFYyy`, `HnFYyy`, `FYyy`, `FY 2026-27`, `fiscal '27` first, in the sentence then in the question. Otherwise the document's forward year: a Q1-Q3 call/deck guides its own fiscal year, a Q4 call or Q4 results filing guides the year after (a Q4 earnings call discusses the year ahead), so KEC's 18 May 2026 "for the year" row is FY27 and its 30 Jan 2026 row is FY26. A bare "Q2" maps to the next quarter with that number after the call's own ("Q1" in a Q4 call is Q1 of the next year), and a quarter preceded by versus/from/than/against is a comparison base and skipped ("5% versus Q4" names no target quarter). **T-105 adds the horizons `medium_term` and `long_term`**: "that's just medium term, we maintain a guidance of 20% to 25%" and "the longer-term growth guidance of 23% to 25%" are real corridors but not a fiscal year, and the Q2 FY27 call states FY27 26-27%, a medium-term 20-25% and a longer-term 23-25% together; labelling them FY27 would let one overwrite the other.
- **Precision rules, T-056 loop 3 (4 Nov 2026), a hand read of all 136 rows.** Nine wrong-row families are now filtered, each with the rule that removes it: (A) a bare quarter in a backward-looking phrase is not the target period — `PAST_Q` ("Q1 results", "Q2 performance", "in the Q3 level", `revenues`, `profit`, `sales`) and a reporting verb behind it (`PAST_VERB`) make "Q2" context, so a Q1FY27 call's "Q1 results ... guidance 1.5% to 3%" is FY27, and the explicit period label nearest the target number now wins (the sentence's own "FY26" over a "Novelis Q3FY26 Earnings" heading printed 90 characters later); (B) "next year" is the year after the document's, not the document's own — a Q2FY26 call's "next year ... INR11,000 crores" is FY27, a Q4FY26 call's "this year ... next year will be INR15,000-17,000" is FY28, "the coming financial year" said 2026-10-28 is FY28, and a period label in the question that is already over is skipped ("we were 12% to 15%" in Aug 2026 is FY27, not FY26); (C) a reported result quoted against the guided range is dropped (`GUIDED_ACTUAL`: "at 23.3% was within the range we guided", "midpoint of the guidance"; `REPORT_BASIS`: "this is how we will report"); (D) an amount spent to date is an actual, blanked before the range parser (`ACTUAL_SPEND`: "$5 billion – $2.7 billion capital expenditures spent" is not a 2.7-5.0 range); (E) a project's whole capital cost is `project_capital_cost`, one row per document, while a year's capex stays `capex`; (F) `nim`/`credit_cost` are read only for a profile company with `lender: true` and sector nbfc or bank (an insurer's growth is not NIM), a segment or business named in the company's `dimensions` before the number stays out of a company metric (`segment_subject`), and `other` needs its guidance word in the number's own clause with no other noun owning it (`other_cued`: an L1 position, an order-book exposure, gross debtors and a fire impact are not targets, "I am targeting ... INR100,000 crores" and "fixed versus variable would be roughly 50%" are); (G) a sentence that ends in a question mark is never a target (a rhetorical "..., okay?" tag excepted), and a page of a transcript whose statements are held elsewhere may only contribute a sentence whose "Name:" label is one of that document's management speakers; (H) an INR amount with no unit word in a crore-scale money metric is `inr_cr`, a running header ("KEC International Limited August 11, 2026 Page 14 of 23") is cut from the sentence, and a number that is a comparison base ("against INR5,000 crores, which we got this year", "INR2,500 crores last year") is not the target; (I) the run dedupes on `(symbol, metric, period, low, high, unit, said_on)` — the same date+values from BSE and NSE or from two pages is one row — without dropping a later date's restatement.
- **The 4 Nov review, a second hand read of all 69 rows (8 wrong, 7 rules now).**  An "impact of X on <metric>" sentence is an effect, not a level (`IMPACT_OF_ON`: "the impact of Optimum Healthcare … on operating margin will be approximately 0.7%"); a hedge is no target (`HEDGE`: "whether it will be 25 or 50 basis points, difficult to quantify"); a spend said in the perfect is past (`PAST_ONLY`: "we have been spending around INR250 crores") while "we have been talking about 8% to 8.5%" is still guidance; a place's share of a split total (`PLACE_IN`: "INR1,000 crores in Orissa and INR600 crores would be in MP") and a market's growth (`MARKET_OWNS`: "China is a large, growing market … 5-7% growth") are not the company's number; a share of a combined business is a share (`SHARE_NOUN`: "the total revenue would be 27% of a combined business"); and "remains at ~$500/t" is the actual when no guidance word comes before the number, while "the AUM growth estimates of AUM remain at 24 to 25%" keeps its row (`REMAINS_AT`, checked against the nearest cue).  The spend family D masks now has its own row: `project_capital_spent`, low = high = the amount, unit `usd_bn`/`inr_cr`, `target_period` = the period the sentence names ("end of FY26" → FY26, "end of Q1FY27" → Q1FY27, "end of Q3FY26" → Q3FY26), same quote and same dedupe key.  One leftover loop 3 reported was settled by T-062: "the cost of production in the Q2 level" now carries `Q2FY26` (the quarter the sentence names, from the filing's own fiscal year), and `checkpages` still holds 145 / 314 because it matches the value and the page, not the period.
- **Kept out:** macro forecasts (GDP, inflation, IMF, repo, "global", "ex-China", CY24) unless the sentence also names a company metric; past measurements (`achieved`, `stood at`, `was around`, `last year`, `grew by`, `improved by`): the number must not sit before every cue, and a sentence with a past marker needs its own explicit forward period ("last year would be 7.5%" is not a target); **a reported quarter's cost** (4 Nov 2026: `down 9% YoY`, `was impacted by ... $54 million`, `came in at $506` — a level that was measured, not guided); **the rate of a tariff or duty** (`RATE_OF`: "232 aluminium tariffs at 50%" is not a 50% margin); facts shaped with today/currently/as of/backlog/market share for `other`; a GNPA/NNPA actual near the chosen number; and a metric word that is far from every number. **T-062 (4 Nov 2026)** adds: a present-perfect movement (`PAST_ONLY`: "yield on assets have come down … 30 basis points") is a measurement; a change ("Reduction of 0.75% to 1%", "a 1% point margin accretion") is the size of the change, not a level (`DELTA_NOUN`, `PCT_CHANGE`); a number taken out of a stated total is a slice, not the total (`SLICE_OF`: "out of INR30,000 crores … INR20,000 crores"); a list of labelled percentages is a customer/business mix, not `other` ("salaried is about 40%, business would be about 34%"); "in the Q2 level" is that quarter of the filing's year (`Q_LEVEL`) and "in the next quarter" the quarter after the call's own (`NEXT_Q`); and a growth sentence owns its number (`subject_ok` reads the whole sentence when the metric's own word is not in it), while a life insurer's IRP/APE is its top line.
- **T-105 (8 Nov 2026): the Q2 FY27 call's targets, the horizon labels and the current row.** The Bajaj Finance call filed 2026-10-23 produced no `guidance` row, so a model answering "what is the FY27 AUM growth guidance" fell back to the April deck's 22-24% instead of the call's 26-27%. The fixes, each in `reality_engine/pilot3/guidance.py`: the `_CUE_V2` commitment phrasings ("on track to deliver", "we remain comfortable … to deliver", "we are clear about adding", "we should deliver", "we'll lower … to"); the count range parser `R_MN_RANGE` and the `new_loans` / `new_customers` / `opex_to_nti` metrics; and the reading of a metric the sentence does not name — a **lender's** unqualified "growth" is its AUM growth (26-27% stated in answer to "what would be the growth guidance"), taken from the sentence or from the previous management statement on the page (`prev`, transcript statements only) and recorded as `guidance_cue_v2_context`. Three guards keep that reading precise: a growth of a line we do not hold as a metric ("fee income growth", "ROA"), a "this number" that borrows its subject from an earlier paragraph, and a previous statement that is not itself forward guidance. `extractor_rule` says which rules made a row: `guidance_cue_v1` (the old rules alone), `guidance_cue_v2` (a v2 cue, one of the new metrics or the million-range parser) and `guidance_cue_v2_context` (the metric is not named in the sentence). On the scratch copy of BAJFINANCE, ETERNAL, INFY the call now yields `aum_growth` FY27 26-27, `medium_term` 20-25, `long_term` 23-25, `new_loans` 60-62 mn, `new_customers` 18-20 mn and `opex_to_nti` 25-40 bps; the five past/hypothetical sentences (AUM grew 26.5%, new loans grew 11%, cost of funds came down, "in a year, we may grow 27%", "Q2 was 10-12 bps lower") stay out. **The tool now serves the current target**: `current_rows()` drops a row when another row of the same symbol, metric and target period comes from a different document with a later `known_at` (already cut at `as_of`, so a row the day could not see never supersedes one it could), keeps every row of the newest document (a call can give two) and puts `superseded_rows` on each kept row; `history=true` returns every row as stored. Files: `reality_engine/pilot3/guidance.py`, `reality_engine/pilot3/queries.py` (`guidance_rows(…, history=False)`), `plugins/reality-data/server/lookups_pilot3.py` (`guidance`), `plugins/reality-data/server/server.py` (`pilot3_guidance(history=)`), `reality_engine/tests/test_pilot3_guidance.py`, `plugins/reality-data/tests/test_lookups_pilot3.py`.
- **Chain.** After a symbol's rows are written, `revisions()` links each row to the previous row of the same metric+period from an earlier document (ordered by `known_at`), so the MCP row carries `previous` (low/high/said_on/direction) and `changed`.
- **State, T-062 on the pilot10 work copy (4 Nov 2026, all ten companies rebuilt).** **90 rows**: BAJFINANCE 6, ETERNAL 11, HDFCBANK 1, HINDALCO 31 (5 of them `project_capital_spent`), HINDUNILVR 3, INFY 15, KEC 13, SBILIFE 5, SUNPHARMA 5; MARUTI has none (its five transcripts are one-page cover letters and its four `deck` documents are the integrated annual report and ESG pages, which state no forward financial target). The keyed targets the T-049/T-056 tickets list are all still found: KEC revenue growth 12-15% FY27, margin 8-8.5% and 7-7.5% FY26 with the cut linked, 50% of the order book fixed/variable, the INR20-25 crore interest cut per quarter, the INR30,000 crore order-intake target; BAJ NIM moderation 10-15 bps FY27, credit cost 1.45-1.60% FY27, AUM growth 22-24% FY27; HINDALCO cost +5% Q1FY27 and +5-6% Q2FY27, downstream EBITDA $250/t FY27. The four wrong rows T-062 named are gone or right: SBILIFE's 14-15% row is `revenue_growth` (its individual APE growth; the margin 26-28% rows stay), MARUTI's customer profiling list is not a row, KEC's INR20,000 crore slice of the INR30,000 crore order intake is gone, and HINDALCO's Q2 cost 3-4% row carries `Q2FY26`. `checkpages run` holds the fixture's 145 / 314 (KEC 29, BAJFINANCE 59, HINDALCO 57) and A1 is 709/898 (every company level; the 694/898 figure in the T-058 note was the smaller database before the added documents). The hand read with seed 20261112 (every row of the small companies, 20 of HINDALCO's 31) reads all right; nothing is left unresolved. The live `reality_engine\data\pilot3\pilot3.db` still needs `--part transcripts` and `--part guidance` (plus `docs_collect --symbols KEC` in the wrapper) before sessions see this. **T-105 (8 Nov 2026) on the scratch copy** (`D:/RealityEngine/pilot10/scratch/t105_dsh.db`, built from pilot10 with `python -m reality_engine.pilot3.guidance --out <db> --symbols BAJFINANCE,ETERNAL,INFY`): 32 → 42 rows (BAJFINANCE 6 → 16, ETERNAL 10 → 10 with one row's period relabelled `Q2FY27` → `long_term` — the "over the longer term … three-year 60% CAGR guidance" sentence, whose old label was the filing quarter — and INFY 16 → 16); 11 new rows, each hand-read as a true target, and no other v1 row changed. The call filed 2026-10-23 now holds AUM growth FY27 26-27, medium_term 20-25, long_term 23-25, new loans 60-62 mn, new customers 18-20 mn and opex-to-NTI 25-40 bps. The live pilot10/pilot3 stores still need `build --part guidance` and an MCP restart.
- **Precision before the loop-3 rules, 40 random rows of a 332-row build (seed 7, 4 Nov 2026, after the T-049 subject rules):** 28 state a forward target cleanly and 12 do not: a past measurement restated ("we laid out as we got to the $525 ... in the 4th Quarter as we have guided", "9-month revenue of 24% Y-o-Y"), a deck line that prints a total cost and a spend in one dash ("$5 billion – $3.2 billion capital expenditures spent"), a generic or conditional level ("generally, margins would be around 8% to 10%", "if it will decline it will be 5 to 7%"), a two-part guidance read as one slice ("H1 6% and H2 8% and overall 7%" stored as 6%), a share read as growth ("20% of the entire SAE"), and a bare answer with no subject in its own sentence. The loop-3 rules remove the dash line and the guided-range actuals; the ceiling is still a sentence with two quantities or a question whose metric is not the answer's; the upgrade path is a tagged sentence classifier, not wider cues.
- **MCP tool.** `pilot3_guidance(symbol, metric=None, period=None, as_of=None, limit=12, history=False)` in `lookups_pilot3.py`, registered in `server.py`: `metric` is a word (`margin` -> `ebitda_margin`, `loans` -> `new_loans`), `period` goes through `norm_period` (FY27, Q2FY27; the horizon labels `medium_term`/`long_term` are served by the default call), rows are newest first and every one carries the target, the quote, the speaker and provenance (document + page, `known_at`); by default only the current target of each metric+period is returned (the older row is dropped, the kept row carries `superseded_rows`), `history=true` returns the whole chain; `as_of` drops later and undated rows and only lets a row known by that day supersede; a miss lists the metrics held. The server instructions route any guidance/outlook/target/corridor question to it first, and `pilot3_sql` lists the table. The live `reality_engine\data\pilot3\pilot3.db` (and pilot10's) needs `--part guidance` (or `--part all`) and an MCP restart before sessions see it.
- **Extractor limits.** Transcripts only when `transcript_statement` has the document; for a transcript whose pages built but whose statements did not, the generic sentence splitter reads the page and keeps a sentence only when its "Name:" label is one of that document's management speakers (an analyst's or journalist's words are dropped). A deck bullet that runs on without punctuation is split at the bullet marker only; chart numbers are not targets; one call can hold several rows of the same metric+period only on different dates (the chain orders them and the date key collapses the rest); the year of a Q4 call's unlabelled "for the year" is a rule, not a fact, so a Q4 call that talks about the year just ended yields the next year.
- **Tests.** `reality_engine/tests/test_pilot3_guidance.py` (32 tests: number ranges and pairs, period rules, fixture metric/period/unit/quote, past measurements and macro forecasts dropped, **reported actuals and tariff rates filtered**, the metric-is-the-subject rules and a share of a total, the revision chain, quote-on-page, `queries.guidance_rows` with `as_of`, the twelve real-database targets on a `.tmp` copy, **plus the T-056 cases: next/coming year forward, the backward-looking quarter, the nearest explicit label, a guided-range actual, `other`'s clause rule, a segment number, a comparison base, the running header, one row per metric+period+value+date with the restatement linked, the project spend beside its total, the seven review leftovers, and the restated estimate that must stay**, **plus the T-058 cases: the worded magnitude with NULL low/high, the 70s bucket, the flattish direction, "will get to" as a cue, the three sentences that must stay out (a guided-range actual, a past exceptional item, a board appointment), CAGR as revenue growth with the EBITDA-CAGR counter-case, the store-day KPI as `other`, and the insurer's margin staying a margin under a profile**, **plus the T-062 cases: the growth sentence against a question's margin metric, the customer-mix list, the slice of a stated total, the "in the Q2 level" quarter and the "next quarter", the reduction/accretion as a change, the IRP/APE top line and a worded direction read from its own words**, **plus the T-105 cases: the 60-62 million new loans, 18-20 MM customers and 25-40 bps opex-to-NTI targets with their `guidance_cue_v2` rule, the AUM 26-27 FY27 target and the medium-term 20-25 corridor read from the growth word and the previous statement, the five past/hypothetical sentences that must stay out, and a three-document fixture for the current-target view (`superseded_rows`, `as_of` before and after the last filing, `history=true`)**). `reality_engine/tests/test_pilot3_speakers.py` (8 tests: the participants block and its document-label guard, the moderator's "with us today" names, bare name lines with the analysts excluded, a Q&A answer after an analyst becoming management, an unplaceable speaker counted but not stored, **a page-numbered footer becoming boilerplate and leaving the quote, and a media call with no moderator opening `qa` at its first journalist**). `plugins/reality-data/tests/test_lookups_pilot3.py` (24 tests, all passing) adds the tool, the revision chain, the search period normalisation (`FY26` echoes `FY26`, never `FYFY26`), the undated-document search and the statements fallback.

### O7. pilot3 embedding retrieval test (T-049, 4 Nov 2026)

**Paid runs, 4 Nov 2026 (Shivam approved $1):** 1B done, 4,606 text pages + 1,451 deck images, **$0.1224** actual (images about 1,000 tokens each, not the ~270 the DeepInfra page suggests); 8B started with `--max-usd 0.45`. Gold file `D:\RealityEngine\pilot3\embed_test\gold.json` (112 questions: 68 commentary, 44 factual; gold = corpus pages holding the exact quote of a right or partly right 4 Nov re-answer, so it leans towards pages bm25 already finds). Eval: `python -m reality_engine.pilot3.embed_test eval --gold D:\RealityEngine\pilot3\embed_test\gold.json --model 1b,8b` (`--out` is the cache folder, not a file).

The pilot answers text questions through `pilot3_search` (bm25). Before any embedding spend, one question has to be measured, not assumed: **does a dense page vector put the page that answers a question above the page bm25 puts there?** `reality_engine/pilot3/embed_test.py` measures it on the pilot3 corpus with the two approved DeepInfra models. It makes **no paid call by itself**: `plan` is offline, `--dry-run` uses a fake client, and the paid run is one command the controller starts with Shivam's $1 approval.

```bash
python -m reality_engine.pilot3.embed_test plan                                    # counts, tokens, cost; no network
python -m reality_engine.pilot3.embed_test embed --model 1b --max-usd 0.25          # text vectors, resumable, budget-capped
python -m reality_engine.pilot3.embed_test embed --model 1b --images --max-usd 0.25 # plus deck page images
python -m reality_engine.pilot3.embed_test embed --model 8b --max-usd 0.50
python -m reality_engine.pilot3.embed_test embed --model 1b --dry-run --out .tmp\embed_dry   # fake client, offline
python -m reality_engine.pilot3.embed_test eval --gold tasks\...\gold.json --model 1b,8b      # writes EVAL.xlsx
python -m pytest reality_engine/tests/test_pilot3_embed_test.py -q                           # 15 tests
```

- **Corpus** (`plan` on the 3 Nov database, 4 Nov 2026): `doc_page` rows joined to `doc` on `doc_key` where `doc_type` is transcript / deck / results / press release / annual report and `doc.known_at >= '2025-04-01'` -- **100 documents, 4,606 pages**: annual_report 8 / 2,349, deck 32 / 1,456, transcript 25 / 420, results 13 / 303, press_release 22 / 78. The text item is one header line (`KEC | deck | <title> | filed <date> | page N`) plus the page text cut at **30,000 characters**; the header is included in the token estimate. 14,651,744 characters = **3,662,936 text tokens at chars/4**. Text is read read-only through `connect_ro`; nothing is written to the database.
- **Deck images.** Every deck page is also a ~**110 DPI JPEG** of its source PDF (PyMuPDF first -- 1.28.2 on the MSI -- else pypdfium2; `plan` prints which). The PDF path is `doc.source_key`, which is pages.db's `source_path` that `build.py` carries into `doc`; a missing absolute path falls back to `REALITY_RAW_ROOT/<doc_key>` (the old `history/...` keys). On the 3 Nov database **100/100 corpus PDFs and 32/32 deck PDFs were found**, so the render path has no gap; a page that still cannot be found or rendered is skipped with a counted reason (`no_pdf`, `render_error`) and never stops the run.
- **API.** DeepInfra OpenAI-compatible `https://api.deepinfra.com/v1/openai/embeddings`, key from `DEEPINFRA_API_KEY` (never printed; absent key stops before any request). Request `{"model", "input", "input_type": "document"|"query", "encoding_format": "float"}` (DeepInfra rejects `task` for Nemotron 3.5 with HTTP 400 "use input_type"; fixed at merge, 4 Nov; the code keeps `task` names internally and maps `search_query` to `query`); an image item is the content-part list `[{"type":"text","text":<header>},{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}]`. Models `nvidia/Nemotron-3.5-Embed-1B-BF16` and `nvidia/Nemotron-3.5-Embed-8B-BF16` at their default dimensions (the length the response carries is printed and stored). Prices per million tokens: 1B $0.015 text / $0.035 image, 8B $0.035 / $0.070. `usage.prompt_tokens` is read from every reply and added to the spend; 16 items per request, 4 requests in flight, 429/5xx retried with 1/2/4/8 s backoff.
- **Cost, 4,606 pages** (plan; the image figure assumes 1,700 tokens/page, which the embed run probes on the first 5 images and prints before continuing): **1B $0.0549 text + $0.0866 image = $0.1416**; **8B $0.1282 + $0.1733 = $0.3015**. Both models, text and images, fit the approved **$1**. The full-corpus dry run spent a fake $0.0549, the same as the plan's 1B text estimate, so the estimate is calibrated.
- **Retries (9 Nov 2026).** HTTP 429/5xx, network errors and a read timeout mid-response (`TimeoutError`, which is not a `URLError`; the 9 Nov p20 run died on one at page 1,984) are retried with backoff, 5 attempts.
- **Budget and resume.** `embed` stops before a request whose projected cost would cross `--max-usd` (the projection is the larger of chars/4 for the batch and the running mean tokens per item), so the spend can never run past the cap by more than one request. Vectors are cached in `D:\RealityEngine\pilot3\embed_test\<model>_text.npy` / `<model>_image.npy` plus `<model>_<kind>.index.json` (`doc_key`, `page`, `kind`; `--out` or `PILOT3_EMBED_DIR` moves the folder). A run skips pages already cached, so a stopped run resumes; a truncated index is cut to the shorter side and a corrupt pair is re-embedded, both with a printed note.
- **Eval.** Gold file = JSON list of `{qid, symbol, question, as_of, gold: [[doc_key, page], ...], date_from?, date_to?, doc_type?}`. A question's pool is that symbol's corpus pages with `known_at <= as_of` (and inside `date_from`/`date_to` on the filing date and the document type when given). Methods: **bm25 alone** (the same FTS5 query the `pilot3_search` tool builds -- up to 12 quoted words OR-joined -- ordered by bm25 over the pool), **dense alone** per model (cosine; the question embedded with `task="search_query"`, the page with `task="document"`), **hybrid** = reciprocal-rank fusion of bm25 and dense (k=60), and **deck text+image max** (a deck page scores the better of its text and image vectors). The report prints hit@1 / hit@5 / hit@10 / hit@50 and MRR per method and the gold rank of every question under every method (``-`` = the method never returned a gold page; a page no method returns is not credited to a later position), writes `D:\RealityEngine\pilot3\embed_test\EVAL.xlsx` (summary + one row per question) and prints the same summary table. Dense coverage per question is printed as `coverage_<model>` so an eval over a partly embedded corpus cannot be read as a fair comparison. The query vectors are the only paid tokens in `eval` (35 tokens for the 3-question dry-run fixture).
- **Drift from the brief.** The brief said to reuse `lookups_pilot3` search scoring; that module lives in `plugins/reality-data/server/lookups_pilot3.py` and importing it pulls the MCP server's `core` module and plugin path. `embed_test.py` therefore rebuilds the same query (12 quoted words, OR) and applies the same pool predicates over the pilot3 database directly; `tests` pin the bm25 order on a fixture. Since 4 Nov 2026 the pilot3 store is also a catalogued reality-data database (`db='pilot3'`, section O8), so a `sql(db='pilot3')` call can read it too; the eval keeps `connect_ro` because it reads `doc_key`/`page` over the whole corpus rather than through the tool's row limit.
- **State, 4 Nov 2026.** `plan` prints the table above and `32/32 deck PDFs found`; a full offline `embed --dry-run --model 1b` embedded all 4,606 pages for a fake $0.0549, and `eval --dry-run` on a 3-question gold fixture (one deck page per company) produced: bm25 hit@1 33% / hit@5 67% / hit@50 100% / MRR 0.461, 1B dense 0% (random vectors, as expected), 1B hybrid hit@50 100% / MRR 0.055. **No paid call has been made.** Next: Opus runs `embed --model 1b --images --max-usd 0.25`, `embed --model 8b --images --max-usd 0.50`, then `eval --gold <the 300-question gold file>` and reads EVAL.xlsx; the question the run answers is whether dense/hybrid beat bm25 on hit@5 and MRR.
- **Paid result, 4 Nov 2026.** 112 gold questions (`D:\RealityEngine\pilot3\embed_test\gold.json`, 68 commentary / 44 factual). Hit@10 / MRR: bm25 35% / 0.18, 1B dense 38% / 0.19, 1B hybrid 46% / 0.22, 8B dense 45% / 0.20, 8B hybrid 52% / 0.23; hit@50 8B dense 82%. `deck_max` equals dense because image cosines run ~0.07 below text cosines, so max() always takes text (method flaw); a deck-only check (`image_test.json`, 52 questions) gives 8B text top-5 42%, image 29%, z-score blend 35%: images add nothing. Spend 1B $0.1224, 8B $0.2683. Report `D:\RealityEngine\reports\2026-11-04_embedding_test.html`.
- **Tests.** `reality_engine/tests/test_pilot3_embed_test.py` (15 tests, all pass in this sandbox): plan counts and cost lines on a fixture database, header/truncation, the image content-part format and a real JPEG render (skipped when no renderer), batching (no request over 16 items, 4 in flight), the budget stop before a batch, a zero budget embedding nothing, resume from the cache making no request, the image probe skipping a page with no PDF, RRF and the hit/MRR metrics on a 3-question fixture, the pool's as_of/date/type filters, bm25 returning the gold page first, `embed --dry-run` + `eval` end to end through the CLI (writing `EVAL.xlsx`), the paid client refusing without a key, and a truncated cache index. The tests build under `.tmp/`, because pytest's own temp root is denied in the DSH sandbox.

### O8. reality-data tool gaps, the BAJ lender ratio and the KEC order gap (T-049, 4 Nov 2026)

The 4 Nov re-answer grade (`D:\RealityEngine\reports\2026-11-04_mcp_reanswer_grade.html`) found five tool gaps and one data gap. No model call and no network fetch was made: every fix is a rule, a default or a catalog entry.

- **`pilot3` is a catalogued database.** It was the one store the catalog never listed, so `schema(table, db='pilot3')` answered "not found" and a model could not discover the tables it was being routed to. `core.DB_FILES` / `DB_ALIASES` (`pilot3`, `pilot`, `p3`; the path honours `REALITY_PILOT3_DB` so the fixture tests read the same file the tools do) and `catalog.DB_SPECS` / `DB_DESCRIPTIONS` now carry it, with per-table auto descriptions and `DATE_COLUMNS` (`doc_page_fts` is hidden: it mirrors `doc_page.text`). The shipped `catalog_cache.json` predates the store, so `catalog._fill_missing` introspects any `DB_SPECS` key the cache lacks on first use (~4 s for pilot3) instead of forcing a full `--refresh`; `catalog_view(db='pilot3')`, `get_schema(table, db='pilot3')` and `sql(db='pilot3')` all resolve through it.
- **`pilot3_sql` text cut.** Every text cell was trimmed to 400 characters with no way to widen it, so an answer about wording could not read the paragraph it needed. `pilot3_sql(query, limit=100, max_chars=400)`: default unchanged, hard cap 8,000, the reply echoes `max_chars`, the tool description and the server instructions say to pass `max_chars=8000` for long page text.
- **HINDALCO diluted EPS FY26 — the basis default.** `pilot3_fin("HINDALCO","eps_diluted","FY26")` returned the standalone 45.31 where 60.20 was wanted: the store held both bases and the standalone row came first. The store was right (consolidated 60.20 / 60.31, standalone 45.31 / 45.40). With no `basis` asked, a mixed reply is filtered to its consolidated rows and the reply carries `basis_assumed='consolidated'`; `basis='standalone'` is the explicit ask. Every row labels its basis (`not_stated` when the store has none).
- **BAJFINANCE FY26 opex / net total income — the annual row.** Only per-quarter rows existed; `ratio_panel` had no `opex_to_net_total_income_pct` at all. `reality_engine/pilot3/ratios.py` adds formula `F_OPEX_NTI` = `100 * (employee_cost + fee_commission_expense + other_expenses + depreciation) / (total_income - finance_cost)` and `_lender_opex()`, which derives one row per fiscal year and basis from the XBRL annual lines (all six inputs required, `known_at` = the max of the inputs, `input_refs` = the six `fa:` rows). FY26 consolidated **33.34%** (opex 17,776.29 cr over NTI 53,323.55 cr), FY25 33.20%, standalone FY26 34.36% / FY25 34.08%. NTI equals the reported net total income (53,324 cr) and the cost components reconcile with the reported pre-impairment operating profit (53,324 - 17,776 = 35,548 cr).
- **KEC order announcements, April-July 2025 — classification, not a fetch gap.** `bse_announcements.ann` holds 18 KEC order filings in FY26 (the first five, 1 Apr - 25 Jun 2025, filed under `Company Update / Press Release / Media Release`, the rest under `Award of Order / Receipt of Order`) and all 18 bodies are held in `pilot60_history/KEC/material_filing`; `raw\material_announcement\KEC` holds two other files and the coverage workbook's `fetch_worklist` does not list them. The five were *in* pilot3 as `press_release` titled "Press Release / Media Release", so `pilot3_docs(doc_type='announcement')` and any order question saw 13 of 18. `docs_collect.py` now types an announcement whose headline announces new orders (`ORDER_HEADLINE`: "new order(s) ... secured") as `announcement` whatever its sub-category, and `_ann_title` titles a filing under the generic sub-category by its headline ("...new orders of Rs. 1,236 crores secured..."). No PDF is missing, so no fetch command is needed: a re-run of `python -m reality_engine.pilot3.docs_collect --out D:\RealityEngine\pilot3\pages.db` and `build --part registry` (or `--part all`) retypes the five on the live database.
- **HINDALCO Q3 FY26 tariff cost — the $34M/$54M rows.** The statement rows are exact and correct: Q3 FY26 (18 Feb 2026 call, 11 Feb 2026 deck) says "$54 million from Oswego fires and $34 million from tariffs"; Q2 FY26 had a $54 million *tariff* impact — two different items sharing 54, which is where a reader crosses them. The wrong *stored rows* were in `guidance`: a tariff rate stored as an FY26 EBITDA margin (50%, from "232 aluminium tariffs at 50%"), "Adjusted EBITDA down 9% YoY" stored as revenue growth, and Q3 FY26 cost actuals labelled FY26 / Q3FY25. `guidance.PAST_ONLY` now rejects `down N% YoY`, `impacted by` and `came in at`; `RATE_OF` rejects a percentage that is the rate of a tariff/duty. On a copy rebuilt with `--part guidance`: HINDALCO 131 -> 117 rows, all 8 wrong tariff rows gone, KEC 381 and BAJFINANCE 148 unchanged, and the twelve ticket targets still extracted.
- **State and commands (4 Nov 2026).** The ratios rebuild on a copy printed the acceptance row:
  ```bash
  Copy-Item "$env:REALITY_DATA_ROOT\pilot3\pilot3.db" .tmp/pilot3_copy.db
  python -m reality_engine.pilot3.build --out .tmp/pilot3_copy.db --part ratios
  # FY26 consolidated 33.3367 pct F_OPEX_NTI, inputs fa:BAJFINANCE:FY26:consolidated:{employee_cost,
  # fee_commission_expense, other_expenses, depreciation, total_income, finance_cost}#<rowid>
  python -m pytest plugins/reality-data/tests reality_engine/tests -q -k "pilot3 or lookups"
  ```
  Tests: `plugins/reality-data/tests/test_reality_data.py` (8 databases in the catalog, `schema('kpi_series', db='pilot3')`), `plugins/reality-data/tests/test_lookups_pilot3.py` (24 tests: `max_chars` default/cap/`bad_max_chars`, the consolidated default with the basis label, the current-target view with `history=true`; the MCP stdio test skips only in a sandbox that blocks child-process pipes), `reality_engine/tests/test_pilot3_ratios.py` (new, 2 tests: the FY26 row with its inputs; no row when an input is missing), `reality_engine/tests/test_pilot3_docs.py` (an order press release becomes an announcement titled by its headline), `reality_engine/tests/test_pilot3_guidance.py` (32 tests incl. the wrong-row assertion, T-105's Q2 FY27 cases and the current-target fixture; the count was 9 when this sandbox run was made). In this DSH sandbox pytest's own `tmp_path` cannot run at all (pytest's `mkdir(mode=0o700)` temp root is unlistable here): the selection gave 105 passed / 22 errors from fixture setup (`test_pilot3_docs` 3, `test_pilot3_kpi` 6, `test_pilot3_ocr` 13) before `test_pilot3_ocr` and `test_pilot3_profile` stopped using it (a local `.tmp` fixture, as `test_pilot3_second_read.py` does); the 3 docs tests were run through a driver with an ordinary directory and pass, and on the controller they run as written. The live `pilot3.db` still needs `docs_collect` + `build --part registry` (order typing) and `build --part guidance` (guidance rows) plus an MCP restart before sessions see them.

### O9. Fast checks for a pilot3 extractor fix (T-049, 4 Nov 2026)

A full rebuild is eight minutes and the whole-database integration tests build it, so a fix round checks one
company and a fixed set of pages instead.

```bash
python -m pytest reality_engine/tests -q -k pilot3 -m "not slow"                          # fix round: 51 s in this sandbox (the tmp_path fixture errors are the sandbox's, see below)
python -m pytest reality_engine/tests -q                                                  # at merge, slow tests included
python -m reality_engine.pilot3.build --out .tmp/pilot3_kec.db --part kpi --symbols KEC   # one company: 125 s
python -m reality_engine.pilot3.checkpages run                                            # fixed pages: found / missing, 5.5 s
python -m reality_engine.pilot3.checkpages make                                           # regenerate the fixture and its baseline
python -m reality_engine.pilot3.regression_set score --all                                # hand-read gate: 0 FAIL required (T-122)
```

- **One company (`build.py --symbols`).** Only the extractors are limited (`extract`, `kpi`, `transcripts`,
  `guidance`); they already delete and rewrite one company's rows. `registry`, `pages`, `stores` and `ratios`
  rebuild every company's rows and ignore `--symbols` (`--help` says so). Measured 4 Nov 2026 on a copy of the
  live database (23,558 pages): full `--part kpi` **502.7 s**, `--part kpi --symbols KEC` **125.1 s**, and the
  KEC rows are identical -- 6,876 rows, the same 6,824 `(metric, fiscal_period, value, doc_key, page)` keys with
  no row on either side only.
- **Fixed check pages (`reality_engine/pilot3/checkpages.py`).** `make` writes
  `reality_engine/tests/fixtures/pilot3_checkpages.json` from the 4 Nov graded answers
  (`D:\RealityEngine\pilot3\answer_run2`, new grade R or P only): every non-zero answer number whose quote maps
  to one to three `doc_page` rows (the quote's first 120 normalised characters occur in the page) on a document
  type an extractor reads -- 314 page numbers. `run` re-extracts only those pages (plus each document's first
  three, so its reporting period is read as in a full build) with the current `kpi` and `guidance` code, from the
  stored page text and, for the table and chart rules, the PDF word boxes of that same page. It works on a
  throwaway copy under `.tmp/`; the live database is only opened read-only. It prints found / missing per company
  with the missing list and takes about 6 s.
- **Baseline, 4 Nov 2026** (recorded in the fixture): **145 / 314 found** -- KEC 29/78, BAJFINANCE 59/113,
  HINDALCO 57/123. A missing number is not automatically a defect: many answers come from the tables and
  narrative of the other sessions (annual-report prose, segment charts), so the count is a floor a change must
  not drop below. The 4 Nov review round holds it at 145 (KEC 29, BAJFINANCE 59, HINDALCO 57).
  `reality_engine/tests/test_pilot3_checkpages.py` runs `run` and asserts every company is at or
  above it (skipped where the live database, the fixture or the raw PDFs are absent).
- **Markers.** `reality_engine/tests/conftest.py` registers `slow`; the two `test_pilot3_core.py` integration
  tests (module fixture `built` -> `build.build(db, "all")`, about 8 min) carry `@pytest.mark.slow`.
  `test_pilot3_checkpages.py` is unmarked: three fast tests (quote mapping, value/unit match, `run` end to end on
  a synthetic page) and the baseline test. In this DSH sandbox the selection gives 115 passed and 20 errors from
  fixture setup only (the `tmp_path` root is denied, as in O8); the controller runs it as written.

### O10. pilot3 profiles: any company list (T-056, 4 Nov 2026)

`reality_engine/pilot3/profile.py` (new) turns the three-company pilot3 build into a build for any company list from one JSON file: `name`, `pages_db`, `raw_root` (with its `manifest.csv`), `out`, `window_start`, optional `price_start` (default `2019-01-01`, T-155) and `companies` (`symbol`, `name`, `bse_code`, `isins`, `sector`, `lender`). The committed profile is `tasks/night_loop/pilot10_profile.json`; `--profile <json>` is taken by `docs_collect`, `build`, `kpi`, `transcripts` and `guidance`, and without it every command behaves exactly as before (the three pilot3 companies into `pilot3.db`, `--symbols` limiting only the extractors).

- **Company literals live in the JSON.** `profile.load` returns a `Profile` / `ProfileCompany`; `profile.company(symbol)` returns the `gap_loop` `Company` the store readers take (db_name and questions empty), `profile.is_lender(symbol)` answers from the profile's `lender` flag (without a profile, the filed interest/premium lines of the default database through `lender.filed_lender`; T-094 removed the old `ratios.LENDERS` list), and `registry`, `stores`, `statements`, `ratios`, `kpi`, `transcripts`, `guidance`, `call_dates` and `docs_collect` read the active profile through these helpers.
- **docs_collect under a profile** reads the raw `manifest.csv` only (`status='ok'` rows; `known_at = dissem_ts`, bucket -> `doc_type`), writes the same `doc` / `doc_page` / FTS tables and makes no store lookup and no directory walk; a bucket with no document (`concall_audio_link`, `skip`), a file not on disk and a row without a dissemination time are counted, not written. `collect_manifest()` is the entry point.
- **No sandbox.** `kpi.extract_company` and `transcripts._transcript_docs` take `sandbox=None` under a profile and read `pages_db` only; the sandbox root is never joined.
- **Window.** `stores.apply_window` deletes rows dated before `window_start` from `fin_quarter_xbrl.period_end`, `fin_annual_line.period_end` (plus `bulk_block_deal.deal_date` and `insider_trade.intimation_date`); **T-155 (9 Nov 2026)** `price_delivery.date`, `index_price.date` and `valuation_daily.date` keep their rows from `price_start` instead (profile key, default `2019-01-01`; `profile.load` refuses an earlier date), so a five-year price or P/E range is answerable on a build whose documents start at `window_start`. `stores.trim_derived` cuts `valuation_daily` at `price_start` (a day whose PE/PB/EV inputs are not known keeps close and market cap with NULL ratios) and `ratio_panel` still at `window_start`. With a profile `compute_start` earlier than `window_start` the rows of `fin_quarter_xbrl`, `fin_annual_line` and `price_delivery` from it up to the window move to `<table>_input` (inputs only; `ratios.build_ratios` reads them through TEMP views); the `price_delivery` copy stops at `price_start`, so main and input never list the same day. The shareholding tables are the exception (T-088): `shp_category.quarter_end`, `shp_holder.quarter_end` and `shp_pledge.quarter_end` keep every quarter from `compute_start` (`stores.HISTORY_TABLES`), since the percentage base and the pledge history are answers, not inputs. No profile, no filter.
- **`--symbols` limits every part** under a profile (`profile.set_scope`), so a profile database built for one company holds one company; without a profile it still limits only the extractors. `--out` and `--pages-db` override the profile's paths.
- **MCP.** `lookups_pilot3.pilot_symbols()` takes the allowed companies from the database's `company` table (T-090: always, for the default database too; `PILOT3_SYMBOLS` is only the fallback when an older build has no such table), so `pilot3_kpi` and the rest serve a profile build with no code change. An HP worker gets the variable from `hp_worker start --pilot-db <path>` (T-070): the file is staged and copied to `C:\RE\data\<basename>` exactly like a `--dbs` file and named in that job's `reality-data` MCP `env`; a missing path is refused, and without the flag the patch is byte-for-byte unchanged.
- **Measured 4 Nov 2026.** Without a profile: `checkpages run` 145 found (29/78, 59/113, 57/123) and `build --part kpi --symbols KEC` on a copy plus the four `--ocr-db` databases reproduces 6,915 KEC `kpi_series` rows exactly (96 s). With the pilot10 profile, MARUTI: `docs_collect` 147 documents / 1,170 pages (17 s); `build` registry 0.2 s, pages 0.5 s, stores 15.5 s, kpi 11.8 s, transcripts 0.3 s, guidance 0.4 s -> `company` 1 row, `doc` 147 all dated, `fin_quarter_xbrl` 164 rows (min `period_end` 2025-12-31), `fin_annual_line` 260, `price_delivery` 516 (min 2025-10-01; T-155 now keeps prices from `price_start`, so a default build holds them from 2019-01-01), `shp_category` 180, `kpi_series` 161; `transcript_statement` and `guidance` 0 because MARUTI's five `concall_transcript` filings are one-page cover letters. The full picture is blueprint section 9.
- **Loop 2 stores and ratios (T-056, 4 Nov 2026; blueprint section 9a).** `stores.py`: `BANK_TAGS` / `LIFE_TAGS` read by taxonomy marker in `_quarter_extras` (a bank's `InterestExpended`, an insurer's `GrossPremiumIncome`), `build_share_fallback` (shareholding-pattern total for every quarter end, written beside the paid-up row; T-073), `build_deals`, `build_insiders`, `build_index_prices` (by ISIN; `schema.py` tables `bulk_block_deal`, `insider_trade`, `index_price`), `apply_window` / `trim_derived` (`INPUT_TABLES`). `statements.py` (profile builds only): bank / insurer annual P&L through `SECTOR_TAGS`, `Capital` + `ReservesAndSurplus` or `ShareholdersFunds` as net worth, lender `cash_and_equivalents` from the cash-flow closing cash, derived `investments` and annual `ebitda`. `ratios.py`: `_input_views`, `_split_factor` (annual EPS restated across a bonus or split), `F_COST_INCOME`, `POINT_IN_TIME` quarter-labelled copies of H1 ratios, one `dividend_per_share` per fiscal year, valuation on the basis that has both a share count and a quarterly statement (T-073), zero dividend yield only with a filed zero cash payout. `profile.py`: optional `compute_start`, `extra_indices`, `price_start` (T-155). MCP: `server.py` and `catalog.py` list the three tables for `pilot3_sql`. Timings on the 10-company copy: stores 140 s, ratios 1.4 s; `--part ratios` is idempotent (identical rows). Tests: `test_pilot3_ratios.py` (7), `test_pilot3_core.py` (bank / life mapping, share fallback, deals and insiders by ISIN, index relative return, annual-line gating), `test_pilot3_profile.py` (`compute_start`, `extra_indices`, `price_start`), `test_pilot3_price_window.py` (T-155).
- **Test:** `reality_engine/tests/test_pilot3_profile.py` (8 tests: committed profile, no-profile defaults, manifest -> pages -> registry/pages/kpi/transcripts/guidance with a nonexistent sandbox root, window filter, `--symbols` scoping, lookups on a `REALITY_PILOT3_DB` database, `compute_start`/`extra_indices`, `price_start` default and refusal). Its fixture PDF wraps its text (`insert_textbox`): a clipped line states no figure, so the KPI part would write no row.
- **Price history from 2019 (T-155, 9 Nov 2026).** `profile.price_start()` returns the profile's `price_start` (default `2019-01-01`; `load` raises `ValueError` on an earlier date). `stores.build_prices` reads the raw `px_nse_adj` / `px_bse_adj` rows from it, `apply_window` keeps `price_delivery` / `index_price` / `valuation_daily` from it, `build_index_prices` computes its lookback returns from it, and `ratios._valuation` starts its day loop there (the only ratios change is that day floor: every input is still filtered by `known_at <= day`). `test_pilot3_price_window.py` pins a 2020 price/index/valuation row on a profile whose `window_start` is 2023-10-01, the `ValueError`, the later `price_start`, and the disjoint `price_delivery_input` copy.
- **Generated profile and no hand lists (T-094, 6 Nov 2026; blueprint sections 7, 7a, 9).** `reality_engine/pilot3/make_profile.py` writes a profile from symbols or ISINs (`python -m reality_engine.pilot3.make_profile <SYM|ISIN>... --name <n> --root <dir> [--raw-root <dir>] --window-start <day> --compute-start <day> --out <json> [--check-db <built.db>]`): name, BSE code and every ISIN from the stores (`symbol_isin_history`, `isin_rekey_log`, `corporate_documents`, `shp_index`, `results_xbrl.filings`, `master_companies`, same-issuer checked), `sector` from `company_industry` joined by ISIN through `reality_engine/pilot3/sector_map.yaml` (kept out of `lexicon/`; 191 basic industries: 135 family, 56 honest `unknown` (T-133 remap, 9 Nov 2026); 1,620 of the 2,041 labelled ISINs in a family, 421 honest unknown), and `lender` from the taxonomy's own list (bank, NBFC, housing finance, microfinance, life and general insurance) independent of the family. The label is tried by every ISIN then the symbol (14 rescued, 2 families); `master_companies.industry` is a second tier only when the taxonomy has nothing (usable for 495 of 5,358, clean map 135, adds 64 companies). Across the 5,358 active companies: 1,638 (30.6%) in a family, 3,720 (69.4%) unknown, 3,309 (61.8%) with no taxonomy row at all (mostly BSE-only; the BSE scrip master is a 420-byte Access Denied page, so those stay `unknown` and are reported). `reality_engine/pilot3/lender.py` is the one filed-line test (`fin_quarter_xbrl` interest/premium lines): `lookups_pilot3._is_lender`, `make_profile --check-db` and the no-profile `profile.is_lender` all call it; the profile itself cannot, because it is written before the database it builds (0 disagreements on `pilot10.db`). `master_companies.sector` is unused. No company list lives in code: without a profile `profile.symbols()` reads the default database's `company` table, and `docs_collect`/`profile` no longer import `gap_loop.company.COMPANIES`; the KEC site-manifest case is a general manifest lookup (a top-level folder named `<symbol>` or `<symbol>_*`); `PILOT3_SYMBOLS`, `kpi.COMPANIES`, `DEFAULT_SYMBOLS` and `ratios.LENDERS` are gone (`test_pilot3_no_company_literals.py` `OFFENDERS` empty, 7 passed; checkpages 146; `test_pilot3_preferred.py` 11 passed). Part 3 (five unseen: DALBHARAT, POWERGRID, TATAELXSI, APOLLOHOSP, DLF) built rc 0 in 270 s `docs_collect` + 814.8 s build (comparatives 405.6, extract 258.3, stores 113.8 s), 151.2 MB build + 218.7 MB pages = 74.0 MB/company; `scale_report --fixed stores=6` projects 311.8 h on one process, 52.0 h on 6 and 501 GB for 6,940. Stores fixed cost measured on 1/2/5 companies: 16.4/27.9/59.9 s -> ~5.9 s fixed + ~10.8 s per company (the earlier 2-vs-10 gap was cold-cache I/O). Full evidence: `.tmp/T-094_report.md`.
- **Loop 3 printed comparatives (T-057, 4 Nov 2026; fix round 5 Nov 2026; blueprint section 9b).** `reality_engine/pilot3/comparatives.py` (`--part comparatives`, after `stores`, before `ratios`, in `all` only under a profile) reads each `results` PDF's **word boxes** (rotated by the page's `rotation_matrix` first) into `fin_quarter_printed`: every P&L column a quarterly table prints (current, preceding, year-ago, ytd, prior ytd, last full year), a canonical `line_item` from `reality_engine/pilot3/lexicon/results_lines.yaml`, rupees, `known_at` = `doc.known_at`, and `check_status` (`xbrl_ok` against `fin_quarter_xbrl`, `sum_ok` from the table's own identities, `repeat_ok` when a DIFFERENT filing printed the same period and value, `unchecked` = stored but never used by ratios). A page must be a P&L table: segment, ratio/margin, non-IFRS reconciliation, `Less:` and bracketed-cost pages are refused. EPS is checked with 2 units of its own printed decimals, never the table's scale. `ratios.py` then takes a quarter the XBRL window does not hold from the earliest filing that printed it, adds QoQ (`F_REV_QOQ`, `F_PAT_QOQ`), YoY from the same filing's year-ago column only when that cell is `xbrl_ok`, `repeat_ok` or `sum_ok` (better check first) and belongs to the year-ago quarter (T-088), TTM from one filing's printed columns decided by the table's shape (`last_fy + ytd - prior_ytd` when it prints a ytd; a Q4 table prints the year; `F_TTM_PRINTED`) when fewer than four quarters are held, and printed full years (`F_FY_PRINTED`). `pilot3_fin` falls back to the table after `fin_quarter_xbrl` (`definition` `printed_comparative`), and `pilot3_sql`/`catalog` list it.
  - **Trap.** `schema.create` DROPS every table it names, so a per-symbol rebuild must not use it: the part calls `schema.ensure` (`CREATE TABLE IF NOT EXISTS` + indexes) and then `DELETE FROM fin_quarter_printed WHERE symbol=?` (HANDOFF 4 Nov: one company's rebuild erased the other nine).
  - **Fast check.** `python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part comparatives --symbols HDFCBANK,MARUTI,KEC --out D:\RealityEngine\pilot10\scratch\w_cmp.db` takes 30-40 s; all ten take about 4 min. `--part ratios --out <copy>` (about 5 s) rebuilds every company from the merged quarters. Measured on the pilot10 copy 5 Nov 2026 (pre-T-073 baseline): 6,685 rows (fix round; 5,587 before), A1 651 -> 682 of 898, `valuation_daily.pe` days BAJFINANCE 188 (244 before the fix), ETERNAL 130 (72), HINDALCO 245, HINDUNILVR 178, INFY 8, KEC 188 (117), MARUTI 130 (6), SBILIFE 6, SUNPHARMA 246, HDFCBANK 11; `pytest reality_engine/tests/test_pilot3_comparatives.py -q` 18 passed.
  - **T-073 store defects (5 Nov 2026; blueprint 9c).** Four general rules, no company named. (1) `build_share_fallback` writes the `shp_category` `shareholding_pattern` total (`source_table='shp_category'`) for every quarter end and basis beside the paid-up row; `ratios._share_count` / `_valuation` prefer it by its own `known_at`, `pilot3_holding` orders it first. (2) `stores.STOCK_COST_TAGS` reads `PurchasesOfStockInTrade` and the finished-goods inventory change from `results_xbrl.facts` (the `quarterly` view lacks them), the same captions are in `lexicon/results_lines.yaml`, and `ratios._gross_margin` (`F_GROSS_M`) = (revenue - materials - purchases - inventory change) / revenue for non-lenders. (3) The printed role pool follows the quarter end and the column count (Q1 "year ended" is `last_fy`, Q4 is `ytd`/`prior_ytd`, a 5/6-column Q2/Q3 carries `last_fy`), `_assign_tokens` matches monotonically so a missing middle cell cannot slide the columns, `_valuation` requires both a share count and a quarterly statement on its basis, and a missing last full year comes from `fin_annual_line` (`last_fy(annual)+ytd-prior_ytd`, stated in `input_refs.ttm`). (4) A YTD flow in a document filed after the quarter ended, with no period in its own sentence, is `fiscal_period='YTD'` with `as_of_date` = filing day; a segment named after a share of the total ("~70% from T&D") keeps the row `total` (`kpi.py`). (5) The pilot10 profile sets `compute_start='2024-07-01'` and lists KEC's earlier ISIN `INE389H01014` and SUNPHARMA's `INE044A01028`: the four quarters before the window are read through `<table>_input` and the ratios TEMP views, so `valuation_daily` has PE/EV on all 269 sessions for every company with a share count from 1 Oct 2025 (was 11-255 PE, 0-245 EV; both counts predate T-155, which keeps valuation days from `price_start`, NULL PE/PB/EV before the first known quarter) and INFY's 2025-11-14 PE is 22.14 on trailing EPS 67.87; the document answer tables still start at the window (0 earlier document rows, 0 `known_at > date`, 0 ratio rows before their period end). EV/EBITDA uses the latest filed annual **or half-year** balance sheet and `input_refs.net_debt` names it (HINDALCO rests on FY26: no derived H1 net debt); lenders keep none. SBILIFE keeps 230 valuation sessions (first exact share count known 2025-11-28) and PE from 2026-01-28. Measured: A1 759/898 (round 1 732), no company below, checkpages 145; `test_pilot3_comparatives.py` 21, `test_pilot3_ratios.py` 12, `test_pilot3_profile.py` 6 of 7 (one pre-existing failure, see blueprint 9c).

## 5. Code tools: outline and typecheck (T-054, 4 Nov 2026)

Retired 4 Nov 2026 (moved to the Recycle Bin, history in `tasks/archive/code-intel_install/`): the `plugins/code-intel` plugin — its AST index and CLI, and the stdio server's core, LSP client and server modules — and its test module.

`plugins/code-tools/` replaces the retired code-intel LSP. A resident `basedpyright-langserver` cost ~800 MB per worker and code-intel answered 1.5% of tool calls (423 of 28,787 over 207 runs); the two tools here run and exit, so nothing stays resident between calls.

- `outline(file)` — `plugins/code-tools/tools.py` walks one file with Python `ast` and returns every class, function and method with `name`, `kind`, `line`, `end_line`, the parent class and the first docstring line.
- `typecheck(files)` — one `basedpyright --outputjson` run with the checkout's `pyrightconfig.json` (120 s cap, the tree killed on timeout), returning `{errors: [{file, line, message}], error_count, seconds}`.

The MCP server is `plugins/code-tools/server.py` (`mcp__code-tools__outline`, `mcp__code-tools__typecheck`; `CODE_TOOLS_ROOT` sets the checkout); `plugins/code-tools/ct.py` is the CLI form the briefs name as the fallback. Wiring: `reality_engine/scripts/run_deepseek_harness.py` (`code_tools_patch` re-roots it at a worktree worker's checkout), `reality_engine/scripts/hp_worker.py` (`mcp_patch`), `.mcp.json`, `pyrightconfig.json`, `reality_engine/scripts/build_worker_context.py` (the pack's section 1) and `plugins/dsh-worker/server/core.py` (`TOOL_INSTRUCTION`); `plugins/dsh-worker/server/progress.py` counts `mcp__code-tools__*` as read-only. `plugins/dsh-worker/server/context_pack.py` now requires the `Evidence:` brief field (seven fields, `Evidence:` after `Accept:`), and `plugins/dsh-worker/server/plugin_server.py` states the seven in the `start_worker` description. The dsh profiles take the row in `tasks/dsh_profiles/code-tools.insert.yml`, replacing the old `mcp-code-intel` block. Tests: `plugins/code-tools/tests/test_code_tools.py`.

## 6. Loop checks: the night loop's frozen evals (T-055, 4 Nov 2026)

`reality_engine/night_eval/` (standard library + sqlite3, no model or network call) turns `tasks/night_loop/GOAL.md` into commands. `qset.py check <dir>` runs the line schema and Phase 1's Q1 sector fit (every `sector_fit` metric and row-need metric in that sector's list of `tasks/night_loop/questions/sector_vocab.json`, i.e. its own ids plus `universal` and `technical`), Q2 coverage (per company: each lens >= 10, orders 1st >= 40 %, 2nd >= 25 %, 3rd >= 10 %, needed document types) and Q3 (order-1 questions need >= 3 variations; two questions of the same symbol above 0.8 normalised token Jaccard are near-duplicates). `qset.py split <dir>` is the fixed split `int(sha256(qid)[:8],16) % 10 < 7` = dev, writing `dev.jsonl` beside the set and hidden to `.tmp/night_eval/hidden.jsonl` (the wrapper moves it; a hidden question is never printed). `answerable.py` scores A1 per need -- a typed-table row (symbol, period, basis, metric, `known_at <= as_of`; a need marked `new_table` names a Phase 2 table and is met only once the db holds it with a row for the symbol) or the `pilot3_search` bm25 page search called in-process (`plugins/reality-data/server/lookups_pilot3.py`, never through the MCP server) -- and lists the dev unmet needs by `table.metric` / `doc:<type>` as the next loop's work list; `--hidden` prints counts only. `guards.py` measures A3 provenance (value in quote, quote's first 80 normalised characters on the cited `doc_page`, `page_missing` counted separately) on the rows a branch added, A4 counts (XBRL disagreement of deck/release/transcript revenue-PAT-EBITDA at the total dimension, kpi periods starting after the document date, `known_at` before the filing, duplicate `doc.sha256`, rows per page above p99, margins > 100 %), A5 (the changed `build.py` parts on a COPY under `.tmp` with a `sitecustomize` that makes every socket connect raise, plus added lines under `reality_engine/pilot3/` scanned for company literals, ISINs, BSE codes, raw-data paths and hashes, plus the protected paths), A6 (the wrapper's test result, `--a6 ok`) and A7 (pages read and build seconds from `--timing`). `decide.py` prints ACCEPT only when A1-dev rises, A1-hidden and every company hold, A3 >= 98 %, A4 counts do not rise, A5 passes and A6 is green, with A7 allowed to rise <= 20 % only with an A1-dev gain of a point. `run_loop.py` launches one hidden `claude -p` session through `reality_engine/scripts/session_runner.py` (Opus, effort medium, <= 150 turns, 2 h, `--disallowedTools` Agent, the worker merge/push tools and `git push`/`git merge`) and prints exit, turns, tokens, `limited`; `audit.py` scans transcripts for reads of `hidden.jsonl` or `D:\RealityEngine\pilot3\answer_run*`. Commands and thresholds: `reality_engine/night_eval/README.md`. Tests: `reality_engine/tests/test_night_eval.py` (fixture sqlite databases, six-question sector sets and a temporary git repository under `.tmp`; `tmp_path` is denied in the dsh sandbox).

Known baseline on the 4 Nov live db (sample, `guards --limit 40`): A3 67 % with 40 cited pages absent from `doc_page` -- the annual-report rows (`fin_annual_line`, `doc_key` like `49222`) cite AR pages the pages part has not stored, so A3 on those rows cannot pass until the ARs are paged. A4 on the same db: 0 duplicate `doc.sha256`, 0 margins > 100 %, 0 periods starting after the document date, 2065 XBRL disagreements (the store carries several conflicting KPI rows per company/period) -- all comparable numbers for "not up".

### O11. pilot3 segments from the raw results XBRL (loop 2, 4 Nov 2026)
Script: `reality_engine/pilot3/xbrl_segments.py`; run it with `python -m reality_engine.pilot3.build --profile <json> --part segments --out <db>`
(`run(db_path, symbols)` returns files, rows, single-segment rows and check failures per symbol). The XBRL files are read through `raw_store` (one `prefetch` per company): since T-102 they live on Drive, and a run that skipped missing local files silently wrote 0 segment rows (8 Nov rebuild lost 1,334 kpi rows until this fix). Why: the results
store keeps only undimensioned totals, so per-segment values were lost at parse time. How:
1. File list from `results_xbrl.db.filings` by the company's ISINs and `period_end >= window_start`; a revision of the
   same period and basis keeps the latest `dissem_ts|broadcast_ts`. Raw files from `raw_market/nse_results_xbrl`.
2. Each context is read for axis, member and period (ids vary by filing). Concepts: `SegmentRevenue`,
   `SegmentProfitLossBeforeTaxAndFinanceCosts`, `SegmentAssets`, `SegmentLiabilities`; life insurers sum net premium,
   `IncomeFormInvestments`, `OtherIncome`, `TransferOfFundsFromShareholdersAccount` (`is_reported` 0) and use `SurplusDeficit`
   as EBIT. Only contexts ending on the filing's period end count. Quarter, H1/H2, 9M and FY contexts all become rows.
3. `Single segment` filings (flag read from the file) write `dimension='single_segment'`, not a filler.
4. Names: leading `(a)` dropped, punctuation collapsed, mapped per company (`_canonical`): names that occur together in one filing never merge; similar names (ratio >= 0.85) that never occur together merge to the spelling in the most filings (tie: latest filing); `raw_label` keeps the name as filed. A single-segment description of 'NA' or empty gives the label "Single segment".
5. `kpi.run` deletes only rows whose `source_type` is not `xbrl_segment`, so a later kpi rebuild keeps them.
6. Check 3 (`reconcile`): segment revenue less `InterSegmentRevenue` against `SegmentRevenueFromOperations`, 1%.
Result on the pilot10 copy: 10 companies, 0 check-3 failures, A1 571 -> 601. Tests: `reality_engine/tests/test_pilot3_xbrl_segments.py`.
Known limits: `kpi_series.value` for these rows is rupees as filed (`unit` inr, scale 1), unlike deck rows in crore.

### O12. Calculator tool and the answer number check (T-072, 5 Nov 2026)
31 of the 120 answer misses in the 600 hand-read answers were a worker's head sum or a ten-times unit slip while the data
was right (a market cap of Rs 32.20 lakh crore for 3.22; gross NPAs of Rs 3,574 crore for 35,736). Two pieces:
1. `pilot3_calc` (reality-data MCP, `plugins/reality-data/server/calc.py`): `+ - * / **`, parentheses and
   `sum/avg/min/max/round` over named inputs with units, walked from the AST (never `eval`). Inputs normalise once to a
   base unit (rupees, count, or a fraction for percent) and compute exactly with `Fraction`, so a unit mistake is an error
   message and never a number: subtracting shares from rupees or multiplying two rupee amounts fails. A money or count
   answer also prints rupees, crore, lakh crore and Indian digit grouping; a percent prints bps. One percentage minus another (T-109, 8 Nov) returns unit `percentage_points` with
   `percentage_points`, `bps` and `relative_change_pct` (27.09% -> 27.44% is +0.35 pp, +1.29% relative), so an answer never
   writes a pp move as a percent. `indian_grouping` is the
   12,34,567 form the answers need. Tests: `plugins/reality-data/tests/test_calc.py` (13).
2. `reality_engine/pilot3/number_check.py`:
   `python -m reality_engine.pilot3.number_check <answers.jsonl | answer.json | dir> [--tsv out.tsv] [--dev dev.tsv]`.
   Reason codes, each its own: `formula_mismatch` (a number's `formula`+`inputs`, or an older `computed: ...` source, does
   not recompute beyond its printed rounding; a source is read WHOLE or not at all -- `^` is an exponent, a root is
   evaluated, a fragment or an unparseable source is a warning, and a fraction is compared at both scales so
   `6,975/6,016-1` = 15.9% still fails 18.4% while `33,986/29,474` passes 115), `unit_slip` (a text amount matching a
   `numbers` entry only at 10x/100x/1000x, or a stated sum/ratio/percent that misses by such a factor; a two-significant-
   digit amount fires only when the answer prints that entry exactly nearby -- two printed digits are chance),
   `stated_working` ("A covers B 101.6 times", "X% of Y is Z", "from A to B, a fall of C", "N% below Y", "A + B = C";
   dates and years are never operands, a sum is read at both scales, a chain with `less`/`minus` is read whole or
   skipped, and a from-to percentage allows the endpoints' own printed rounding), `quote_mismatch` (only when the same
   digits carry a different value behind a different scale word; a value printed literally passes, a computed or ratio
   figure is not judged, and a value merely absent from a cut quote is a WARNING), `source_scale_mismatch` (T-129: a
   money entry's own `source` prints the entry's digits behind a different explicit scale word and the wrong amount --
   MARUTI-127's 4,136 crore sourced as "Rs 4,136 million"; the real amount, 413.6 crore, passes), `bad_grouping` (comma grouping
   neither Indian nor Western). `unmatched_amount` is a WARNING, not a block: prose quotes rounded intermediates an
   answer never lists, and blocking on those fails most honest answers. `--tsv` writes `file, qid, code, severity,
   detail, where`, one row per finding.
   `reality_engine/pilot3/answer_record.py` takes the same CLI as `record.py` (`<SYM> start <qid>`, `<SYM> answer <file>`,
   writing `.tmp/<SYM>_answers.jsonl`) and refuses a failing answer: failures printed, exit 1, a `check_failed` row
   appended; a retry carrying `"check_override": "<reason>"` records with `check_failures` and `check_override` attached.
3. Replay on 5 Nov (round 2) over the ten files of `D:\RealityEngine\pilot10\answer_a2`: 600 answers, 26 flagged, 37
   failing findings (unit_slip 24, formula_mismatch 10, stated_working 3); that run contains the 10 known misses. On the
   256-row dev set
   (`t072_dev.tsv`): 10 of 16 `arith_miss` caught (ETERNAL-057, ETERNAL-124 via sums, HDFCBANK-022/030/033/097,
   SUNPHARMA-116, INFY-019, KEC-119, BAJFINANCE-123, SBILIFE-117) and 3 of 240 graded-right answers flagged: two are real
   slips in the numbers list the grader missed (a gross-premium row ten times short of its own source; components ten times
   the answer text) and one is a false alarm (43.6 lakh crore of earning assets beside a 4,360-crore per-10bps row whose
   unit text quotes the same digits). Missed, and why: ETERNAL-082 (a market cap with no `numbers` entry and no stated
   formula), ETERNAL-124 (the sum has an unstated base), ETERNAL-126 (a 20%-of-volume scaling over a base in another
   sentence), HDFCBANK-063 (the percentage sits 57 characters before "from" and the same sentence holds a second range),
   KEC-109 (an H2 per-quarter division), KEC-110 (the bps claim's operand pair cannot be bound: 7-7.5% against 5.0% gives
   the 200-250 bps the text states). Tests: `reality_engine/tests/test_pilot3_number_check.py` (16).

### O13. Second reading an answer: its prose against its own numbers (T-083, 5 Nov 2026)
The re-run hand read put 89 of the 136 misses on a misread of the answer's own material. Three of those classes a
careful reader sees without the store: prose that contradicts its own figures (a growth series called "halving" when it
fell about a third; a margin series called "steady" while it falls), a cause with no figure, quote or named source, and an
answer that does not fit its question (four quarters asked and two given, a change dated before the window asked, a
standalone figure set against a consolidated one). `number_check.py` owns the arithmetic and is unchanged; this step
reads prose only and fixes nothing.
1. `reality_engine/pilot3/second_read.py`:
   `python -m reality_engine.pilot3.second_read --answers-dir <dir> --qids <file> --out <flags.jsonl>
   [--pass-no N] [--parallel N] [--limit N]`. It reads the `<SYM>_answers.jsonl` `event=answer` row for each qid (the
   last one when a qid has two) and `<SYM>_questions.json`, and sends the question, the prose and the answer's own
   `numbers` rows (value, unit, period, source, quote, `formula`/`inputs`; 40 rows, quotes cut at 200 characters) to
   `beam-free` (`reasoning_effort` low, 4000 output tokens, `x-opencode-session` from `go_session.session_id` on one
   stable job name per pass and the pool lane, `record_usage` to `tasks/ledgers/spend.jsonl`). Resumable: a `qid` +
   `pass_no` already in `--out` is skipped, so pass 2 is the same command with `--pass-no 2`. One row per answer:
   `qid, pass_no, status, flags, dropped_flags, in_tok, out_tok, finish, attempts, error`.
2. Flags carry `kind` = `contradicts_own_numbers` | `unsourced_cause` | `question_misfit`, plus `claim` and `why`. A
   script check, not the model: `claim` must be a contiguous span of the answer prose after whitespace normalising
   (case-insensitive, wrapping quotation marks ignored); a flag that fails is dropped and counted in `dropped_flags`,
   never kept. A `question_misfit` about something missing may leave `claim` empty only when its `why` names a content
   word of the question. A truncated or unparseable reply is retried once and then recorded as `truncated` /
   `unparseable` / `api_error` / `rate_limited` -- never as "no flags"; HTTP 402 or a billing body stops the run
   (exit 3), and a missing key exits 2 before any call.
3. Dev run on `D:\RealityEngine\pilot10\answer_a3\t083_dev.tsv` (46 `read_miss`, 233 `right`, 25 `arith_miss` /
   `absent_miss` / `store_miss` that this step cannot see): pass 1 flagged 28 of the 46 `read_miss` answers, 19 of them
   for the graded fault (41%, target 50%), and 43 of the 233 `right` answers. Read flag by flag, those 43 hold 22 false
   alarms (9.4% of `right`, inside the 10% target) and 21 real slips the grade missed: a count ("six consecutive
   quarters"/"four targets") larger than the answer's own list, a quote attributed to the wrong call date, an operating
   margin labelled an EBITDA margin, a consolidated ratio set against a standalone one. Pass 2 agreed with pass 1 on the
   flagged / not-flagged verdict for 261 of 304 answers (85.9%); pass 1 cost 606,448 input and 207,505 output tokens
   (free model, ledger still records the tokens at $0). A single pass is a sample: the model is not deterministic.
   Three prompt rounds were run; round 3 is the best and is the prompt in the module. Kinds it cannot see: an item the
   store holds and the answer says it does not (a deck page, a macro series), a data fact the answer alone cannot show
   (a terminology error, an index move, a 200-day average before the price history starts), a cost the store exposes
   through period/basis labels the `numbers` rows did not keep, and a count of periods split across two answers.
   Tests: `reality_engine/tests/test_pilot3_second_read.py` (17, fake client, no network).
4. Hold-out, read by Opus (`answer_a3\t083_holdout_qids.txt`, 296 answers; flags in `answer_a3\second_read\`, the
   worker's dev files in its `worker_dev` folder): pass 1 flagged 22 of 43 `read` misses, 16 for the graded fault
   against a pass mark of 18, so the test failed; nothing calls this module in the answer path. The numbers in item 3
   are the worker's own reads. Same-sentence flags given for another reason count in the 16 (three of them). Pass 2
   adds one more answer. The 39 flagged right answers split into 18 false alarms, 11 clear slips and 10 unsupported
   causes; 21 of the 39 were read from the flag alone.

### O14. Financial-line answers: one preferred figure per period (T-088, 6 Nov 2026)
Store fixes 1 and 2 of the T-087 report. Six general rules, no company name in code; the measured results are in
`docs/PILOT3_BLUEPRINT.md` section 9d.
1. **Preferred comparative, `lookups_pilot3.fin`** (`_preferred`, `_printed_cell_ok`). A quarter's rows are grouped by
   (measure, period, basis) and ONE row returns: the newest filing known at `as_of`, `preferred: true`,
   `restated: true` when it differs from the first printing, and `alternatives` = the other distinct values with
   `filing_date`, `role` (current / preceding / year_ago / xbrl), `definition` and `check_status`. Tie on the filing
   date: XBRL > `xbrl_ok` > `repeat_ok` > `sum_ok` > a clean unchecked cell. A printed cell that failed its check can
   still be a genuine restatement (Bajaj Q2 FY26 19,992.38), so it is admitted when its `raw_token` is one printed
   number; a token carrying letters or a currency word is refused (`displayable_printed`, T-090). The `as_of` cut happens before the election, so a date before
   the restatement gets the older value. Annual rows pass through unchanged (their `definition` already separates
   reported / derived / company-stated).
2. **Same quarter for growth, `ratios._printed_year_ago`.** The base is the current filing's own `year_ago` cell
   for that line when its check is `xbrl_ok`, `repeat_ok` or `sum_ok` (`sum_ok` means the year-ago column added up,
   which is the comparative a growth uses: HINDUNILVR Q2 FY26 15,919 in the Q2 FY27 filing; its first printing
   16,241 is pre-restatement, T-088 round 2). Where one filing printed two cells for the line the better check wins
   (`xbrl_ok` > `repeat_ok` > `sum_ok`), so INFY's cash-flow "Total income" `sum_ok` cannot beat the XBRL-confirmed
   revenue cell. The cell's `fiscal_period` must equal the year-ago quarter. With no such cell the printed quarter
   store (`_quarters`) is used and the base ref is suffixed `@fallback` (38 rows on the copy); QoQ's preceding
   quarter is label-checked too, and a mismatch refuses the row rather than using another quarter (`_fiscal_q`).
   INFY Q2 FY27 consolidated 8.276 -> 10.6855%; HINDUNILVR Q2 FY27 14.4921 and Q1 FY27 10.0527 (restated bases).
3. **Stated and derived together, `lookups_pilot3.ratio`** (`_stated_ratios`). The `ratio_panel` rows carry
   `definition: derived` with formula and input refs; the company's own figure for the same ratio in `kpi_series`
   (the metric name or its `_pct` form) returns beside it as `definition: company_stated` with quote and page, for
   every period asked. Company rows only (`entity` = symbol), the consolidated basis first, then `conf_rank` and
   `known_at`; a subsidiary's figure is never the company's.
4. **Entity apart from basis, `kpi_series.entity`.** `kpi.py` adds the `entity` column (`SCHEMA`, `NEW_COLS`, `COLS`,
   `_row_entity`, `_row_basis`): the company's symbol or the subsidiary the row's dimension / page heading /
   paragraph names (`_entity_tokens` holds the lexicon's entity tokens and printed names, so a segment word like
   'commercial' is never an entity). `basis` only ever says consolidated / standalone / not_stated (the subsidiary
   token that used to live there moves to `entity`; a basis word stored in `dimension` becomes `basis`).
   `_entity_before` returning a reporting-basis token (the company's own name) is ignored. `page_basis` now also
   reads an entity heading printed in the page's footer ("Executive summary - Bajaj Housing Finance"). `kpi()`
   normalises an older build's `basis` token to `entity`, lists the company's rows first, labels `entity` and
   collapses exact duplicates (same metric, entity, dimension, period, value, unit).
5. **Trailing twelve months, `ratios._panel`.** `pat_ttm` (`F_PAT_TTM`) and `pat_before_exceptional_ttm`
   (`F_PAT_BE_TTM`) for every company with the last four quarters; the row's `input_refs` are the four `pat`
   quarters, and the before-exceptional row appends each quarter holding a non-zero `exceptional_items` **with its
   amount** (`fq:SYM:Q3FY26:consolidated:exceptional_items=-2652200000`). `ratio()` parses `input_refs` into
   `inputs` for these two metrics.
6. **The two INFY annual-line claims, `stores.build_annual`.** `_concatenated_value` drops an unverified
   (`value_check='not_found'`) fact whose value matches none of the two or more numbers its `value_raw` prints
   (917,626,822,725 from "9,176 (FY26); 8,227 (FY25)"). `_ar_page_bases` maps the ar_facts document to its pages.db
   page (sha256) and `_statement_basis` reads "the Company" / "the Group" wording, overriding a stored basis that
   says consolidated for both the standalone and the consolidated note (3,749 -> standalone, 9,176 -> consolidated).
8. **The election in the data, `reality_engine/pilot3/preferred.py` (T-090).** The preferred-comparative rule of
   item 1 has one home now: `order_key` / `elect` / `evidence_rank` / `displayable_printed` are the moves of
   `_preferred` / `_evidence_rank` / `_printed_cell_ok`, and `lookups_pilot3.fin` calls `elect`, so the tool and the
   stored columns cannot drift. `preferred_from` / `preferred_to` on `fin_quarter_xbrl` and `fin_quarter_printed`
   give the window, in whole YYYY-MM-DD days, in which a row is THE figure: preferred at day D when `preferred_from <= D` and
   (`preferred_to IS NULL` or `preferred_to > D`), one row per (symbol, line_item, fiscal_period, basis) at any D, and
   `fin_quarter_current` is the row preferred now. The new build part `preferred` writes it: it ALTERs the columns onto
   an older database, runs for `profile.symbols()` (`--symbols` limits it), and costs **0.1 s** for the ten pilot
   companies (7,330 windows, 5,408 keys). Re-run it after any part that rewrites those rows (`stores`,
   `comparatives`). The tie-break ends with `-rowid` (the first stored row) so moving the rule changed no answer:
   on the copy, 3,295 quarterly keys compared old vs new are **0 changed**, and `pilot3_fin` vs the columns is
   **0 differences**. Annual lines are not elected: 67 keys hold more than one row but one filing's values share
   its `known_at`, so the rule would pick by rowid (reported, not forced).
7. **Rebuild a copy, never the live file.** `stores` uses `schema.create`, which DROPS its tables: run
   `--part stores` for ALL companies (scope it with `--symbols` and the other companies' rows are deleted);
   `comparatives` and `kpi` rewrite one symbol at a time.
   ```
   # copy D:\RealityEngine\pilot10\pilot10.db -> .tmp\pilot10_w.db (sqlite3 backup, read-only source)
   python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part stores --out .tmp\pilot10_w.db
   python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part comparatives --symbols INFY,BAJFINANCE --out .tmp\pilot10_w.db
    python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part preferred --out .tmp\pilot10_w.db
   python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part ratios --out .tmp\pilot10_w.db
   python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part kpi --symbols BAJFINANCE --out .tmp\pilot10_w.db
   set REALITY_PILOT3_DB=.tmp\pilot10_w.db      # the MCP lookups then read the copy
   python -m pytest reality_engine/tests/test_pilot3_preferred_data.py -q    # 6 passed
    python -m pytest reality_engine/tests/test_pilot3_preferred.py -q          # 11 passed
   python -m reality_engine.pilot3.checkpages run                             # 146 found (29/59/58), default pilot3.db
   ```
   `checkpages run --db .tmp/pilot10_w.db` finds 0/314 because the fixture's 81 `doc_key`s are the
   `pilot3.db` keys while pilot10 stores `SYMBOL/family/uuid.pdf` (the untouched live pilot10.db gives 0
   too). `preferred` must be re-run after any later part that rewrites the two quarter tables.
   The live `pilot10.db` still needs `stores` (all ten), `comparatives` (INFY, BAJFINANCE), `preferred`, `ratios` and `kpi`
   (BAJFINANCE) before a question sees the fix, plus an MCP restart. Measured on the copy: FIN preferred 19,992.38 cr
   with 20,180.76 as its alternative (as_of 2026-01-01: 20,180.76); INFY Q2 FY27 YoY 10.6855%; Bajaj ROE Q2 FY27
   stated 20.6 / derived 17.914, FY26 stated 18.1 / derived 16.958, Q1 FY27 stated 20.4; `kpi('BAJFINANCE','roe_pct',
   'FY26')` 12 values with the company's 9 first and `entity` on every row; the Q1 FY27 "cost of funds was 7.21%" row
   is `bhfl`; PAT TTM 22,066.48 cr on four inputs and 22,331.70 cr before exceptional with Q3 FY26 named; FY26
   `lease_liabilities` 9,176 consolidated / 3,749 standalone. Growth: **1 value changed** from live (INFY Q2 FY27
   consolidated 8.2762 -> 10.6855, base 44,490 `year_ago` `xbrl_ok` of the same filing); HINDUNILVR is back on its
   live values (Q2 FY27 14.4921 = 18,226 / 15,919 `year_ago` `sum_ok`; Q1 FY27 10.0527 = 17,341 / 15,757; Q3 FY26
   5.6891 and Q4 FY26 -0.5474 also same-filing `year_ago` cells), as are the MARUTI and SUNPHARMA rows the first
   round moved. 38 growth rows carry an `@fallback` base ref. Tests in this sandbox: `test_pilot3_preferred.py` 11,
   `test_pilot3_kpi.py` 96 + 6 tmp_path
   fixture errors (sandbox), `test_pilot3_ratios.py` 4 + 8 tmp_path errors run with `.tmp` as the writable root: 8
   passed, `test_pilot3_comparatives.py` 21, `test_pilot3_core.py` 27 + 2 tmp_path errors (driver: 2 passed),
   `test_pilot3_xbrl_segments.py` driver 5 passed, `test_pilot3_checkpages.py` 4.

### O23. Linked and missing call transcripts (T-157, 9 Nov 2026)

19 of the 70 not-right pilot20 answers failed only because the call text was not held: one-page transcript cover
letters (Adani Ports 13, IHCL 2, Havells 1) whose page text or link annotation names the real PDF, and calls with
no transcript document at all (Pidilite Q2 FY27). `reality_engine/pilot3/linked_transcripts.py` resolves both
(`--store <db> --raw-out <dir> [--symbols ...] [--apply]`, report-only without `--apply`), stores each PDF through
`raw_store` and inserts `doc` + `doc_page` rows with the FTS kept in step; `--apply` on a copy of
`D:\RealityEngine\p20\p20new.db` added 14 of the 16 linked stubs and the PIDILITIND and APOLLOTYRE missing calls
(16 documents, 300 pages, 0 skipped). The method, the per-company table and the tests are in
`docs/PILOT3_BLUEPRINT.md` section 9l. Follow-up 9 Nov: `BSEClient.fetch_corporate_announcements` now reads every
50-row page up to `ROWCNT` (it read page 1 only), and `bse_candidates` also tries *Analyst / Investor Meet - Outcome*
PDFs that read as a call (HAVELLS files transcripts that way); 7 tests in `test_linked_transcripts.py` + 3 in
`test_bse_announcements_paging.py`. 16 held call transcripts were typed `announcement` across p20/u8/q12 (T-159); on
10 Nov 2026 `docs_collect` retypes 15 of them from their pages (`docs_collect.reconcile_doc`, section O3), measured
read-only against the four stores.

