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
│   ├── raw_store.py        # Content-addressed raw files
│   └── config.py           # Paths, PRAGMAs, API headers, and thresholds
├── plugins/                # MCP servers: reality-data, dsh-worker and others
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

`status` reads `plugins/dsh-worker/runtime/jobs/*/status.json`,
`tasks/efficiency/worker_reviews.jsonl` and `.tmp/job_watch_acks.jsonl`, and only job folders whose
`status.json` changed in the last 48 hours. Lines are `RUNNING <job> <minutes>m,
<tool calls> tool calls`; `STALLED` when a running job's `worker_activity_at` is
older than 10 minutes; `ENDED BADLY ...` for failed, lost, cancelled or
lease-expired jobs with no review row; and `FINISHED, NEEDS REVIEW <job> <branch>` when a job
finished in the last 48 hours, has no review row (`id`) and is not done yet: merged branches and
merge subjects count as done (three local `git` calls, skipped when nothing needs it), and so does
a branch that no longer exists (deleted after review; an empty branch list means `git` did not
answer and proves nothing). STALLED and RUNNING come first whatever their age; the rest sort
newest first, so the 12-line cap drops the oldest history and never a live job. A registered
non-worker process is `STALLED` when its log has not changed for its own quiet window: the
`--stall-seconds S` given to `add`, else `JOB_WATCH_REGISTERED_STALL_SECONDS`, else 5 minutes (an
OCR run commits every ~20 pages, so a slow one registers a longer window and stops raising false
stalls that block the Stop hook), and `ENDED` when its `--pid` is gone; a
registration without a pid keeps `wait` watching while its log is still changing, then stalls. Its
record is `.tmp/job_watch.json`. Exit code is 0 in every case and a corrupt record is skipped.

`wait [--timeout-seconds N] [--poll-seconds 20] [--ignore-existing]` first reports anything already
waiting for review: before it takes its baseline it returns the existing `STALLED`, `ENDED`,
`ENDED BADLY` and `FINISHED, NEEDS REVIEW` lines, so a finish that landed while the session was
busy is never swallowed (`--ignore-existing` restores the old behaviour of hiding those lines in
the baseline). It then polls and exits 0 as soon as a line moves to STALLED, ENDED or FINISHED
that was not in that state in the baseline, or as soon as no job record is active and no live
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
`.tmp/job_watch_acks.jsonl`, whose ids `status` treats exactly like `worker_reviews.jsonl` ids, and
removes a registered name from `.tmp/job_watch.json`. `ack --all-ended` acks every `ENDED` and
`ENDED BADLY` line shown; `STALLED` and `FINISHED, NEEDS REVIEW` are left for a real look.

Fixture and worktree overrides: `JOB_WATCH_REPO_ROOT` (defaults to this checkout),
`JOB_WATCH_ACKS`, `JOB_WATCH_STATE`, `JOB_WATCH_WAIT_DIR`, `JOB_WATCH_REGISTERED_STALL_SECONDS`
(default 300, the registered log-quiet window when the record has no `--stall-seconds`) and the
existing `DSH_WORKER_RUNTIME_DIR`.

First measured `status` run (2026-11-02, 284 job folders): 0.36 s wall (0.29 s in process), one
running job and eleven failed/needs-review lines. Tests: `python -m pytest
reality_engine/tests/test_job_watch.py -q` (37 tests) and the real-subprocess stress suite
`reality_engine/tests/test_job_watch_stress.py` (12 scenarios: finish before the baseline,
running to finished within two polls, corrupt status during a poll, 40 jobs, a finish past the
12-line cap, a registered job stalled without a pid and a registered pid that exits, a
hard-killed waiter plus pid reuse, two waiters, Stop-hook latency over 40 jobs (measured 0.4–2.0 s
across seven runs on the MSI; the suite fails above 3 s), timeout line).

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

`reality_engine/pilot3/` builds ONE SQLite database for KEC, BAJFINANCE and HINDALCO by scripts only (no model, no network), so the pilot questions are answered by plain SQL. Part A (the core, this section) is `schema.py` (DDL), `registry.py`, `stores.py`, `ratios.py`, `queries.py`, `oracle.py`, `call_dates.py` (transcript call dates, used by `registry.py` and `kpi.py`) and `build.py`; part B (`kpi.py`, `transcripts.py`, `lexicon/`) is a separate worker's; part D is `statements.py` (below). `__init__.py` finds the read-only stores (`REALITY_DATA_ROOT`, else this checkout's `reality_engine/data`, else the main checkout's) and sets `REALITY_DATA_ROOT` before `gap_loop.prepare` is imported.

```bash
python -m reality_engine.pilot3.build --out .tmp/pilot3.db --part all    # registry | pages | stores | ratios | extract | kpi | transcripts | guidance | all; 484 s on 4 Nov 2026 (23,558 pages)
python -m reality_engine.pilot3.oracle --db .tmp/pilot3.db --tables core [--detail]
python -m pytest reality_engine/tests/test_pilot3_core.py -q              # 26 tests; the 2 integration ones build the real db (marked slow, about 8 min)
```

- **Tables** (every fact row carries symbol, isin, period, basis, value, unit, scale, `known_at` from the filing record, and its source: doc + page, or source db + table + rowid/file). `company` (every ISIN a symbol has had: `symbol_isin_history` plus ISINs only other stores use, e.g. shareholding under `INE296A01016` / `IN9038A01010`), `doc`, `doc_page` + FTS5 `doc_page_fts` (copied from the collector's pages.db, the sandbox pages only for documents pages.db lacks; no PDF re-read; a `needs_ocr` page takes the OCR text and its `ocr_conf` from `build.py --ocr-db`, method `ocr_rapid`), `share_capital` (paid-up / face value per filing, plus split / bonus events and ISIN windows), `fin_quarter_xbrl` (every quarter of `results_xbrl.quarterly`, both bases, 21 XBRL items, long form; revised filings stay as separate rows keyed by `known_at`), `fin_annual_line` (closed caption lexicon over `ar_facts`, `stores.LEXICON`, plus the part D XBRL / deck / annual-report rows below; columns `definition` = reported / xbrl_reported / xbrl_derived / company_stated and `period_type` FY / H1 / Q), `dividend_event`, `price_delivery` (NSE and BSE daily OHLC, delivery, cumulative split factor and adjusted close, from the truth snapshot), `shp_category` (`shp_index` promoter/public per quarter plus holder categories from `D:\RealityEngine\raw\nse_shp_xbrl_pilot` parsed with the stdlib; 2025-05 taxonomy files give fractions, normalised to percent by checking promoter + public ~ 1), `formula` + `ratio_panel` (derived, `is_derived=1`, `formula_id`, `input_refs`, `known_at` = latest input), `valuation_daily` (market cap, trailing EPS restated to the day's share basis by the cumulative split factor, P/E; P/B, EV/EBITDA and dividend yield fill only where `fin_annual_line` has net worth, net debt or dividend per share), and `guidance` (one row per forward-looking numeric target; extractor and rules in O6). **Transcript dates (T-049 review, 4 Nov 2026):** a transcript's `filing_date` and `known_at` are raised to the call date printed in its first pages (`reality_engine/pilot3/call_dates.py`, `known_at = max(filing record, call date)`), because a filing record can date a transcription before the call it transcribes — KEC's Q4 FY26 call, held 18 May 2026, carried the company-site publish date 18 Feb 2026 and answers dated the call from it. `python -m reality_engine.pilot3.call_dates` prints the table (doc_key, stored filing, stored known_at, call date in the text, new dates) for every held transcript and lists the ones no call date was read for: 142 transcripts, 0 unread, 3 filing dates raised (all KEC), 0 known_at raised on 4 Nov 2026.
- **Reads go through the gap loop's copy specs** (`prepare.store_copies`) widened to all ISINs, so the SQL is not duplicated. Rows are read from the real stores, not the sandbox copies, so the one-year window of the sandbox `results_quarterly` is gone (28-31 quarters per company).
- **Definitions.** EBITDA = pre-exceptional PBT + finance cost + depreciation - other income (matches KEC's own 291 crore for Q1 FY27); no EBITDA / EBIT metrics for BAJFINANCE (a lender's finance cost is its cost of goods). FY values are sums of the four filed quarters; FY basic EPS is the sum of quarterly EPS (approximation, noted in `formula`). Company-defined EBITDA (Hindalco FY26 38,097 crore, KEC Q1 FY25 margin 6.5%) differs from the XBRL-derived one and shows as a mismatch, not a failure to fix quietly.
- **Oracle** (`oracle.py`): the newest `status='answered'` row per qid of each sandbox is the reference; `T048_QUESTION_COVERAGE_2026-11-03.xlsx` maps a question to its table; each number of the answer becomes one fixed SQL shape of `queries.py` (`px_on`, `px_extreme`, `fin_quarter`, `fin_annual`, `shp`, `shares`, `ratio`, `valuation`), compared at 0.5% (or half a unit of the oracle's last printed decimal) across crore / million / rupee scales. Numbers whose inputs sit outside part A (AUM, order book, segment EBITDA) are counted apart. First run (3 Nov 2026), questions / reproduced / mismatched / not reachable: ratio_panel 55 / 23 / 1 / 31, price_delivery 21 / 21 / 0 / 0, fin_quarter_xbrl 18 / 14 / 0 / 4, fin_annual_line 25 / 18 / 3 / 4, shp_category 9 / 4 / 0 / 5, valuation_daily 3 / 3 / 0 / 0 (not reachable = a missing table or a question with no check-passing answer).
- **Part D (T-049 D, 3 Nov 2026): the unreachable questions closed by script.** `statements.py` (new) adds, with no model and no network:
  - *XBRL balance sheets, cash flows and annual P&L* into `fin_annual_line` (new columns `definition`, `period_type`): year-end (`FYyy`) and half-year (`H1FYyy`) filings of `results_xbrl.db` (`facts`, contexts `OneI` and year-to-date durations; consolidated and standalone; BAJFINANCE from the NBFC and integrated taxonomies). `definition='xbrl_reported'` = a tag as filed; `'xbrl_derived'` = sum or difference of filed tags: `net_worth` (equity attributable to owners), `total_borrowings` (non-lender: current + non-current; lender: borrowings + debt securities + subordinated + deposits, matches the 4,35,112 crore the call quotes), `net_debt` (borrowings - cash - other bank balances - current investments; not for a lender), `capital_employed` (assets - current liabilities), `capex` (-(PPE + intangibles purchases), cash-flow sign), `trade_receivables`. Values are rupees (`scale` 1); `doc_key` = the XBRL file, `source_rowid` = `file#facts rowid`, `known_at` = dissemination time.
  - *`company_stated`* rows beside the derived ones, never merged: (a) the `stores.LEXICON` now also picks the company's own ratio-note measures from `ar_facts` (net debt including acceptances, total debt including leases, net working capital days, debtor days, ROCE, ROE, net debt / EBITDA) and keeps blank-basis rows as `basis='not_stated'`; (b) `build_company_stated` reads deck / call / press-release / result pages by script: table rows (a label line followed by numeric lines, mapped to the nearest period-token header group only when the column counts agree, `%` columns dropped) and sentences ("EBITDA margins have increased by 70 bps to 6.5%", "net debt, including acceptances is at INR 6,722 crores"); quarter rows have `fiscal_year` `QnFYyy`, `period_type` `Q`. A plausibility gate drops mis-mapped segment rows (EBITDA within 25% of the XBRL-derived one, margin within 3 points, net debt within 40%, leverage 0-15x); the build log prints how many were dropped. Pages come from this database first, then from the collector's `D:\RealityEngine\pilot3\pages.db` (opened read-only, optional); a page used from there is copied into `doc` / `doc_page` so the quote can be checked here.
  - *Annual-report statement pages* (`build_ar_statements`): consolidated / standalone cash-flow and balance-sheet pages of annual reports that `pages.db` holds and this database does not (the Hindalco FY26 report filed 30 Jun 2026: 28 rows; its operating cash flow 10,250 crore equals the XBRL figure).
  - *Dividends*: `dividend_event` (NSE corporate actions, one row per event; final / special by ex-date April-September belongs to the year that closed in March, interim October-March to the year closing next March; `known_at` = broadcast date or the ex-date, which is later than the declaration) and the per-year `dividend_per_share` / `special_dividend_per_share` lines (as declared on the then share basis, so Bajaj FY25 shows 44 + 12 before the split).
  - *Lender quarter fields* in `fin_quarter_xbrl`: `interest_income`, `impairment_financial_instruments`, `fee_commission_income / expense`, `net_interest_income` (= interest earned - finance costs, `is_reported` 0) for BAJFINANCE; the NBFC and integrated taxonomies both use `InterestEarned`, `FinanceCosts`, `ImpairmentOnFinancialInstruments`. Fiscal-year sums of them are in `ratio_panel`.
  - *Balance-sheet ratios* in `ratio_panel` (FY and H1 periods, formulas F_BVPS, F_DE, F_ROE, F_ROA, F_ND_EBITDA, F_ROCE, F_REC_DAYS, F_INV_DAYS, F_PAY_DAYS, F_NWC_DAYS, F_CUR; closing balances over trailing-four-quarter flows, 365-day year; ROCE and ROE use closing capital employed / net worth, not averages). `valuation_daily` now fills P/B, EV/EBITDA from the XBRL-derived net worth and net debt, and dividend yield from the trailing-12-month dividends restated by the split factor.
  - *Lender NIM (T-051, 3 Nov)*: formula `F_NIM` / metric `nim_pct`, lenders only (Bajaj Finance, `ratios.LENDERS`), in `ratio_panel` beside the other balance-sheet ratios: the period's quarterly `net_interest_income` (from `fin_quarter_xbrl`, itself derived as interest earned - finance costs) summed, annualised by x4/n quarters and divided by the average of the balance-sheet `loans` at the period start and end (`fin_annual_line`, `xbrl_reported`; kpi-series AUM is too stale to use — its newest `aum` row is `known_at` 2024-01-29). `is_derived=1`, `formula_id='F_NIM'`, and `input_refs` names every quarter and both loan-sheet rows; `known_at` is the latest input. A NIM the company states itself stays its own `kpi_series.nim_pct` row, never merged into the derived one. `book_value_per_share` (F_BVPS) has FY25 and FY26 rows for all three companies where net worth and a share count exist (Bajaj FY26 183.34 on the post-split share count, FY25 1557.43 pre-split, as filed); `roce` (F_ROCE) has them for KEC and HINDALCO, and is deliberately absent for BAJFINANCE because a lender has no EBIT here (finance cost is its cost of goods).
  - *Shareholding*: the 2025-05 taxonomy files for every quarter to 30 Sep 2026 are already in `D:\RealityEngine\raw\nse_shp_xbrl_pilot` (their header has no `Symbol`, which hid them); the category aliases (`MutualFundsOrUTI`, FPI category one / two) were missing, and `fpi_total` is the pattern's own `InstitutionsForeign` line for those files (Bajaj 30 Jun 2026: mutual funds 9.63%, FII/FPI 20.21%). Nothing needs fetching. T-051 (3 Nov): promoter, mutual-fund and FPI holding by quarter answer in one query for all three companies, e.g. `SELECT quarter_end, category, pct FROM shp_category WHERE symbol='KEC' AND category IN ('promoter','mutual_funds','fpi_total') ORDER BY quarter_end`; `stores.MEMBERS` maps both taxonomy spellings, and `build_shp` keeps every ISIN in `symbol_isin_history`, so older rows sit beside the current ones: BAJFINANCE `INE296A01024` (2024-06-30..2025-03-31) beside `INE296A01032`, HINDALCO `IN9038A01010` beside `INE038A01020`. Coverage: promoter and public 23 / 20 / 22 quarters from 2021-09-30; the SHP-XBRL categories (mutual funds, FPI category one / two, `fpi_total`) 11 / 9 / 11 quarters from 2024-06-30. A quarter can carry two `promoter` rows when the `shp_index` copy and the SHP-XBRL parse are the same filing; `queries.shp` orders the XBRL row first, so an answer reads one value. Test: `test_shp_rows_under_an_older_isin_are_copied_to_the_symbol`.
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
- **`kpi_series`** rule ids in `extractor_rule`: `table_v1` (label row + period header row, values paired to header columns by x position; segment from a left-margin heading at or just below the row), `chart_v1` (bare number row over a period axis, titled by a short lexicon label with a unit; skipped when several series share one axis), `sentence_v1` (label ... value [unit] period [vs value period] in running text), `sentence_pair_v1` (period taken from the nearest earlier "A v/s B" header), `sentence_default_v1` (period = document reporting period; lowest confidence, filter it out for strict use). Rows: symbol, metric, dimension, value, unit, scale (1e7 crore, 1e6 usd_mn, 1e3 kt), period_type, fiscal_period (Q3FY24, FY24, 9MFY24), as_of_date, basis, doc_key, page, quote, known_at, raw_label, raw_value, `source_type` (the document type the row came from: deck, results, press_release, transcript, annual_report, announcement, so a reader can filter a call's number away from the deck's), confidence and conf_rank. A call's number keeps its own row at the bottom of the confidence order (`conf_rank` two ranks lower, floor 1: 1,399 transcript rows on 3 Nov 2026), so "INR1,600 crore" from a Q&A never ranks as the deck's order book. Metric names follow the schema; `credit_cost_bps` stores bps only (a % figure is converted x100, noted by raw_value). `usd_bn` is converted to usd_mn, mt to kt, and `MM` (the decks' million) is read as `mn`. A value whose quote is not a literal substring of the page text is never stored. **Period labels:** 31 March closes the Indian fiscal year, so a stock figure dated "as on 31 March 2026" is `FY26` with `as_of_date` 2026-03-31 (an explicit "Q4 FY26" header stays `Q4FY26`); a Q4 document (annual-results deck or call) defaults its unlabelled figures to the fiscal year, and a comparison-period mention ("last year in FY '25") never becomes the document's period.
- **Segment mix tables (`mix_v1`, 4 Nov 2026).** A table whose title names the metric ("Business segment wise AUM - Consolidated") and whose rows are segment names is a mix: one row per line with the segment as `dimension`, the Total line as `total`. The value column is the latest period on the page, preferring the column whose entity heading ("Consolidated | BFL | BHFL") is the page's entity (`page_basis`), so the consolidated 31 Mar 2026 column is read and not BFL's or BHFL's. At least three segment lines are required, so a product sub-table (Home Loans / LAP under "AUM - Mortgages") is not mistaken for the mix. Two chart/text rules sit beside it: a donut chart's percentages are paired with its legend in printed order (`chart_v1`) under `<metric>_mix_pct` (`order_book_mix_pct` 63/27/7/2/1 from "Order Book – 31 Mar'26", `order_intake_mix_pct`, `revenue_mix_pct`), the run belonging to the nearest title with no other chart title between them; and a business-wise revenue bullet block ("•Revenues of Rs. 15,883 Cr" ... "T&D") stores one `revenue` row per segment. BAJFINANCE AUM at 31 Mar 2026 thus holds mortgage 1,62,077, consumer 1,04,485, rural 25,234, rural_sales 10,559, sme 51,570, commercial 33,839, auto 15,011, gold 17,831, urban_sales 37,430, las 33,247, 2w3w 4,288+8,325, cv_tractor 3,881, mfi 2,198 and total 5,09,975; KEC FY26 revenue holds T&D 15,883, civil 3,823, renewables 516, cables 2,217, transportation 1,555, oil_gas 258.
- **Segments and entities (T-049, 4 Nov 2026).** A segment word labels a table value only when the row's own label names it, when a text-only heading row above the row starts at or left of the table's first period column, or when the heading sits in the band above the period header and does not start right of that column. A page title ("Novelis, Aluminium and Copper Businesses"), a page footer, and a segment data row ("Copper 673 907 918") therefore no longer label the rows around them: the HINDALCO Q4FY26 / Q1FY27 consolidated EBITDA 11,197 and business-segment EBITDA 10,812 are `total`, not `copper`. In running text a segment word counts only inside the figure's own sentence; a share clause ("63% of our unexecuted order book") may look back 400 characters. KEC FY26 order book is 36,267 `total` and 23,000 `T&D`. `page_basis` reads the entity from the deck page heading ("Financial summary – Bajaj Housing Finance" → `bhfl`, "… – Bajaj Finance" → `standalone`, "Business segment wise AUM - Consolidated" → `consolidated`), so Bajaj's standalone AUM 3,72,986 and BHFL 1,40,706 are tagged instead of being `total` with an unstated basis.
- **Periods (T-049, 4 Nov 2026).** A period printed between the label and its value ("GNPA and Net NPA as of 30 September 2025 stood at 1.24%") is used instead of the document period, so that row is Q2FY26 not FY26; a quarter a later deck reprints for comparison keeps its own period and takes the later document's `known_at`. A prose line laid under a distant table header is not a table row (it used to take that header's column, e.g. Q4FY20 for "as of 31 March 2021"): any row label with a verb (stood, was, grew, compared, against …) is skipped by the table rule, and a value must be a whole token, so "2W" and "B2C" are not read as numbers. A ratio or stock figure dated 31 March (GNPA at "31 March 2025", AUM at "31 Mar 2026") is also stored under its Q4 label (Q4FY25, Q4FY26) beside the fiscal year: the quarter end is the year end, and the quarterly trend question was missing Q4; a flow (revenue, PAT) stays annual only. **A period can never begin after its document was filed** (`kpi.keep_period`, `kpi.period_start`): a row whose fiscal period starts after the document's `known_at` is dropped and counted as `period_after_doc`. The 4 Nov grade found 2019-era filings labelled Q1 FY27 because `June 26, 2019` was read as "June 2026" — the `MON_Y` pattern took the day for a two-digit year (now refused when a four-digit year follows: "June 26, 2019" is no period at all), and the misread date then became the document's default period. A transcript's `known_at` is raised to its call date (O1) before that test, so a call's own rows survive it.
- **`transcript_statement`**: one row per sentence of management speech (md, ceo, cfo, mgmt, ir) with speaker, role, section (prepared|qa), topics (comma list, `other` if none), period_discussed and period_source (sentence|call), numbers_json (value, unit, period, raw), statement (whitespace-normalised), quote (literal slice), is_fragment (cut by a page break; stored on the page where it starts). Analysts and moderator are not stored; speakers who cannot be classified are counted in the run summary and not stored. Cover-letter text before the first real speaker is dropped. **Speaker rules (T-056 loop 3, 4 Nov 2026).** Three rule families place a speaker, no company name in code and `lexicon/topics.yaml`'s `people` untouched: (1) a **participants block** on the first three pages — a heading line (`CORPORATE PARTICIPANTS`, `Management representatives:`, `ANALYSTS`, `JOURNALISTS`) then name/title pairs, or a one-line "1. Name – Title"; management titles go through `_title_role` (cfo / md / ir / mgmt) and a name under an analysts/journalists heading is an analyst, never stored; a document label in the block ("Investor Call Transcript") is not a person; (2) the moderator's **"we have with us today A, B and C"** sentence names the management team; (3) **bare name lines** (2-4 capitalised words, no colon) are speaker marks only when the document has fewer than five real colon marks — the six colon-style transcripts never enter that path — and then only for a name in the participants block or a name line repeated 3+ times with speech after it (a participant's name followed by its title is not a mark). In the Q&A a name that answers right after an analyst three or more times, and was never introduced as an analyst, is `mgmt` (`after_analyst`); everyone else stays `unknown` and is only counted in `unknown_speakers`. A running footer whose page number changes is boilerplate (`boilerplate_lines` normalises digits before the repeat count), so it is masked and never enters a quote; and a media call has no moderator, so the moderator-keyed Q&A marker never fires — when a document has no moderator, the first participants-block journalist/analyst opens `qa` (4 Nov review). **Measured on the pilot10 copy:** ETERNAL 691 rows over 4 documents (Akshant Goyal cfo 474, Albinder Singh Dhindsa md 179, Kunal Swarup mgmt 38; Vijit Jain and Aditya Soman not stored), INFY 2,478 over 4 (Salil Parekh md 1,360, Jayesh Sanghrajka cfo 831, Rishi Basu mgmt 232, Nandan Nilekani mgmt 55), KEC 1,803 (unchanged); the participants block also recovered HDFCBANK's Keki Mistry (+102) and Kaizad Bharucha (+63), HINDALCO's Steve Fisher (+447) and SUNPHARMA's Dilip Shanghvi (+214) and Kirti Ganorkar (+58), because their names were never in the lexicon. BAJFINANCE, HINDUNILVR and SBILIFE are byte-for-byte unchanged; MARUTI stays 0 (its five `concall_transcript` filings are one-page cover letters). **Input (3 Nov 2026):** the transcript extractor reads the same documents as `kpi.py` — the pilot3 db's own `doc_page` when the `pages` part has built it (pages.db documents and their RapidOCR text, doc keys already the pilot3 ones), else the sandbox `docs`/`doc_text`. Reading only the sandbox had left `transcript_statement` on the sandbox's calls — 16,189 rows in all, with BAJFINANCE's newest call 2024-02-03 (925 rows) and HINDALCO's 2024-02-20 (971) while the held transcripts run to 2026-08 (KEC's sandbox does hold its 2026 calls: 14,293). With the pilot3 pages it holds KEC 14,294 rows over 63 documents, BAJFINANCE 4,626 over 22, HINDALCO 4,559 over 17 (23,479 in all). **Speaker turns:** a management introduction may carry a composite title ("Mr. Rajeev Jain, Vice Chairman and Managing Director", "Mr. Sandeep Jain, COO and CFO") — the words before the role are allowed; a known name is matched through an OCR slip or a short form ("Stish Pai" = "Satish Pai", "Dev Ahuja" = "Devinder Ahuja") when the surname agrees and the first name is a prefix or 0.8-similar. **Call period:** the "FY 2026 fourth quarter" / "fourth quarter of FY 2026" forms were read with the groups swapped (a `KeyError`); they now give `Q4FY26`.
- **Known limits (measured 4 Nov 2026, with `--pages-db`).** 37,213 rows (KEC 7,179 / BAJFINANCE 19,084 / HINDALCO 10,950; 35,588 on 3 Nov: the prose-as-table rows are gone and the mix/chart/business-revenue rules add their lines); 6,494 of them FY25-FY27 on 3 Nov. Generic labels (`margin`, `ebitda`, `revenue`) over-match in text-heavy pages, so read the confidence tier; a segment is reliable where the row's own label, a heading row or the figure's sentence names it (table, donut and business-revenue pages); `needs_ocr` pages (110 / 361 / 1,181 with pages.db) are extracted only after `pilot3.ocr` has read them and `--ocr-db` is passed.
### O3. pilot3 document collection (T-049)

`reality_engine/pilot3/docs_collect.py` (no model, no OCR, read-only on every store) collects every held document of KEC, BAJFINANCE and HINDALCO as dated page text for the pilot3 core database. The T-048 sandboxes held only `pilot60_history` (newest page 2024-03) and the BSE feed; the real store is wider.

```bash
python -m reality_engine.pilot3.docs_collect --out D:\RealityEngine\pilot3\pages.db [--symbols KEC,BAJFINANCE,HINDALCO] [--coverage <xlsx>]
```

- **Where it looks.** Folders named by NSE symbol or BSE code anywhere under `D:\RealityEngine\raw` (three levels: `pilot60_history\<SYM>\<bucket>`, `annual_report\<SYM>`, `deck\<SYM>`, `material_announcement\<SYM>`, `decks\bse\<code>`, `nse_announcements\*\attachments\<SYM>`), the legacy pile `D:\RealityEngine\pdfs\<SYM>\<TYPE>` and the old `reality_engine\data\pdfs|decks`; plus the sha256-named folders (`decks_full`, `concall_pdfs`, `kec_transcripts`, `results_pdfs`, `results_notes_refetch`, `deck_page_text`), where a file is taken only when its name (= its sha256) is a hash the stores record for one of the company's ISINs (`corporate_documents.sha256_hash`, `deck_sources`, `deck_figures.pages`, `ar_docs`, `raw_documents`). Every ISIN of `symbol_isin_history` (truth snapshot, else the store copy) is used, so BAJFINANCE's ISINs before and after 2025-06-16 both count. The same bytes filed under several announcements (a results PDF comes with the board-meeting outcome and again with the results filing) make one `doc` row dated by the earliest dissemination; every filing (NEWSID, attachment, `known_at`) is listed in `source_record.filings` and every path in `source_record.paths`. `doc_type` comes from what a store says about the exact file (sha256), else the BSE sub-category, else the folder; an `announcement` under the AGM sub-category with 100 pages or more is retyped `annual_report` (`retype_agm`).
- **Dating (filing records only).** The company site's transcript manifest (KEC), `bse_announcements.ann` by NEWSID or attachment name (the GUID in the file name), `corporate_documents` by sha256 / `bse_newsid` / id, `deck_sources`, `ar_docs`, `pilot60_history\manifest.csv`, NSE announcement jsonl. `doc.known_at` is the raw dissemination timestamp (`DissemDT`); the 15:30 IST day shift is the core builder's job. `doc_date` is the crawl date and is never used. A file no record dates keeps `known_at` NULL and counts as undated. `doc.isin` is the ISIN valid on the filing date. **A transcript cannot be known before its call** (T-049 review, 4 Nov 2026): the collector keeps the filing record as it reads it, and the pilot3 build raises both dates to the call date printed in the document (`call_dates.py`, applied in `registry.build_doc`/`build_pages`, so `doc`, `doc_page` and every row derived from them inherit it; the KPI extractor applies the same clamp to its own transcript rows). A call date more than 400 days after the stored date is refused (a stray header date), and only the first three pages are read, so a dated comparison in the body never moves a document.
- **Tables in `pages.db`.** `doc(doc_key, symbol, isin, doc_type, title, filing_date, known_at, source_path, sha256, pages, source_record, known_at_source)` and `doc_page(doc_key, page, text, method, known_at)` with the FTS5 index `doc_page_fts`: the sandboxes' `docs` / `doc_text` columns plus `symbol`, `isin`, `source_path`, `sha256`. `method` is `script_text` (PyMuPDF text layer, 50 characters or more) or `needs_ocr` (empty text; `pilot3.ocr` reads those pages and `build.py --ocr-db` copies the result into `doc_page` as `ocr_rapid`). A re-run skips a document whose sha256 and pages are already stored. `doc_type` is one of `annual_report`, `deck`, `transcript`, `results`, `press_release`, `announcement`, `audio_link`, `other`.
- **`DOC_COVERAGE.xlsx`** (beside `pages.db`). `summary`: per company and type, documents, pages, `needs_ocr` pages, undated, newest filing date and `known_at`. `missing`: the FY25 and FY26 annual report; for Q1 FY25 to Q1 FY27 the results filing, investor deck and earnings-call transcript; announcements newer than the newest held document; BSE announcement attachments whose headline is held but body is not. `fetch_worklist`: each such headline with NEWSID, attachment and date. `runs`: counts per run, appended.
- **Fetching what is missing** uses the existing fetcher only: `python -m reality_engine.scripts.fetch_pilot60_history --fetch --universe D:\RealityEngine\pilot3\universe3.csv --window-start 2024-04-01 --window-end 2026-10-20`, with `REALITY_DATA_ROOT` set to the main checkout's `reality_engine\data` (a worktree's data folder is empty). It writes `raw\pilot60_history\<SYM>\<bucket>\<newsid>.pdf` and appends to `pilot60_history\manifest.csv`; the next `docs_collect` run picks the files up. Its routine-skip rule (loss-of-certificate, Reg 74(5), newspaper, trading-window and PIT-code notices) is why those headlines stay in `fetch_worklist`.
- **State, 3 Nov 2026** (`pages.db`, `DOC_COVERAGE.xlsx` under `D:\RealityEngine\pilot3`): KEC 621 documents / 5,454 pages, BAJFINANCE 629 / 9,391, HINDALCO 749 / 8,412; 958 of 23,257 pages are `needs_ocr`. Newest `known_at`: BAJFINANCE 2026-10-19, KEC and HINDALCO 2026-10-16. What remains in `fetch_worklist` (46 / 117 / 152 headlines) is the routine notice types the fetcher skips on purpose, plus one KEC large-corporate disclosure, one BAJFINANCE record date and 8 text-only announcements with no attachment. Not held because not yet filed or not in any feed: Q2 FY27 results, deck and call for all three, and the BAJFINANCE/KEC/HINDALCO announcements after 28 Sep / 16 Oct 2026 (the BSE feed in `bse_announcements.db` ends there; NSE announcement records exist for none of the three).
- **Test:** `reality_engine/tests/test_pilot3_docs.py` (fixture stores and PDFs: dating, dedupe, `needs_ocr`, FTS, idempotence, coverage workbook).

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

Two gates enforce it, on `main` only; `python reality_engine/scripts/doc_gate.py --install` writes
both hooks:

- `.git/hooks/pre-commit` lints the board whenever either tracker file is staged, and keeps
  `tasks/TASKS.md` at 150 lines or fewer.
- `.git/hooks/commit-msg` refuses a message whose `T-<digits>` are all absent from both tracker files, or that names none and has no
  `No-ticket: <reason>` line. `merge_worker` puts the brief's ticket into the merge commit; it does
  not close it.

A worker brief carries `Ticket: T-014` or `No-ticket: <reason>`; a T-number absent from the main
checkout's `tasks/TASKS.md` is refused as `ticket_unknown`, and the brief then carries that one row.
The start gate is `plugins/dsh-worker/server/core.py` (the refusal and the row attached to the
brief) with its field check in `plugins/dsh-worker/server/context_pack.py`, and the tool description
in `plugins/dsh-worker/server/plugin_server.py` states the same field.
`reality_engine/scripts/context_guard.py` is the PostToolUse hook that asks Claude to write the
wrap-up at 400,000 tokens and again at 440,000 (session limit 450,000), once each per session.

## 4. Rule and chain-of-command ledger (T-042)

Every gate pass or block is one JSON line in `tasks/efficiency/rule_events.jsonl`
(gitignored, created on demand); `$DSH_RULE_EVENTS` overrides the path.

- `reality_engine/scripts/doc_gate.py` logs one event per pre-commit run on `main` (rule
  `doc_gate`, or `start_files` when the line limit is the block) and one per commit-msg run
  (rule `ticket`, carrying the commit's short subject).
- `plugins/dsh-worker/server/core.py` logs every start refusal: `permission_required` and
  `permission_invalid` (`start_gate_permission`), `brief_incomplete` (`start_gate_brief`),
  `ticket_unknown` (`ticket`), and `peak_hours` / `peak_hours_imminent` (`start_gate_peak`).

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

### O4. pilot3 precision, growth formulas and local OCR (T-049 E, merged unfinished 3 Nov)

- `reality_engine/pilot3/kpi.py`: generic labels (margin, revenue, ebitda) count only on table rows or sentences that also carry a period and a unit; segment comes from the table's row or column header; a chart value takes its period from the nearest axis label; every row has a confidence tier (table_row > table_chart > sentence > sentence_default) and readers prefer the highest. Lexicons in `reality_engine/pilot3/lexicon/` were tightened to match.
- `reality_engine/pilot3/queries.py`: growth, share and mix are formulas over stored rows, not extracted values: `kpi_value`, `kpi_growth` (YoY/QoQ via `prior_period`), `kpi_share`, `kpi_mix`, `book_to_bill`, `coverage_years`, `kpi_fy_sum`; `ratios.py` and `oracle.py` use them.
- `reality_engine/pilot3/ocr.py`: local RapidOCR (ONNX, CPU or DirectML; no model call, no network) for pages with no text layer, 300 DPI grayscale, into table `ocr_page` with word boxes in PDF points and mean confidence; resumable (`--max-seconds`). Pages come from three sources: `pages.db` `doc_page` rows with method `needs_ocr` (PDF from `doc.source_path`, doc_key kept exactly as `build.py` writes it to `doc_page`), sandbox `doc_text` `needs_ocr` pages of documents pages.db does not hold, and the empty-text pages of the `decks_full` PDFs `deck_figures` cites. A page already stored under a key naming the same document (a sandbox `doc_alias` key, or the `decks_full/<sha>` key) is skipped, so no page is read twice. `--pages-db` (default `D:\RealityEngine\pilot3\pages.db`) chooses that source; `''` disables it. `reality_engine/pilot3/hp_ocr.py` (T-052) re-reads the same page set on the HP with Microsoft TextRecognizer at 300 DPI grayscale: `plan` resolves each page's PDF exactly as `pending()` does (old `history/…` keys mapped through `doc_alias`) and copies only those PDFs, `run` starts the resumable `hp_ocr_pages.py` driver as a hidden session-0 task and waits, `fetch` writes `ocr_textrec.db` with the same `ocr_page` columns plus `low_conf_numbers` and `error` (`method='ocr_textrec'`, word boxes in PDF points), `compare` writes `OCR_COMPARE.html`, `cleanup` removes the package, certificate, tasks and copied PDFs from the HP. A page that will not render at 300 DPI or still fails after two retries keeps an error row. `kpi.py` reads `ocr_page` and marks rows with the row's own method and `ocr_conf`; `registry.py` and `kpi.py` prefer `ocr_textrec` over `ocr_rapid` when several `--ocr-db` hold the same page.
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
- **Test:** `reality_engine/tests/test_pilot3_ocr.py` (fixture pages.db, sandbox and OCR dbs and a tiny PDF; `ocr_page` monkeypatched, no real OCR: pages.db keys, alias/decks dedupe, `--pages-db ''`, `doc_page`/FTS fill, `kpi --ocr-db` merge, and the method choice — `ocr_textrec` wins over `ocr_rapid` in either db order, in the registry and in the kpi merge).
- `reality_engine/pilot3/kpi_oracle.py`: the KPI and transcript oracle report (was a `.tmp` script): `python -m reality_engine.pilot3.kpi_oracle --kpi <db> --tr <db> [--detail]`.
- Next: the controller rebuilds `pilot3.db` with the four OCR databases and reruns both oracles; the HP page OCR itself is complete (above).

### O5. pilot3 in one database, served by the reality-data MCP (T-049 F, merged 3 Nov)

- `reality_engine/pilot3/build.py` and `registry.py` load documents and pages from `D:\RealityEngine\pilot3\pages.db` (sandbox pages only where pages.db lacks a document; `doc_alias` maps old sandbox keys) and run the extractors into the same file; the real database is `reality_engine\data\pilot3\pilot3.db` (gitignored, 142 MB on 3 Nov). `schema.py` and `__init__.py` carry the new tables and path. `--ocr-db` may be given once per company OCR database (T-052): the `pages` part writes an `ocr_page` text into its `doc_page` row (the method from the `ocr_page` row, `ocr_textrec` preferred over `ocr_rapid`; `ocr_conf` kept, `doc_alias` used for a sandbox key) before the FTS index is built, so `doc_page_fts` and `pilot3_search` find the OCR text; the `extract` part passes the same databases to `kpi.py --ocr-db`.
  ```bash
  python -m reality_engine.pilot3.build --out reality_engine\data\pilot3\pilot3.db --part all --ocr-db D:\RealityEngine\pilot3\ocr\ocr_KEC.db --ocr-db D:\RealityEngine\pilot3\ocr\ocr_BAJFINANCE.db --ocr-db D:\RealityEngine\pilot3\ocr\ocr_HINDALCO.db --ocr-db D:\RealityEngine\pilot3\ocr\ocr_textrec.db
  ```
- `plugins/reality-data/server/lookups_pilot3.py` (read-only via `connect_ro`, small replies, every row with provenance: table, source document + page or store row, `known_at`; `as_of` drops later and undated rows) backs nine tools registered in `plugins/reality-data/server/server.py`: `pilot3_kpi`, `pilot3_fin`, `pilot3_ratio`, `pilot3_holding`, `pilot3_statements`, `pilot3_docs`, `pilot3_search` (FTS over doc_page), `pilot3_guidance` (the forward targets of O6) and `pilot3_sql` (bounded). The server's instructions route KEC, BAJFINANCE and HINDALCO to them first, and a guidance/outlook/target/corridor question to `pilot3_guidance` before the other text tools. **`pilot3_kpi`** orders by the extractor's `conf_rank` descending, then a deck/results/press-release/annual-report row before a transcript row, then dimension total and `known_at`: the first row is now the best source (3 Nov 2026). Its SQL window is 30x the reply size (4 Nov 2026): at 3x, a measure restated in many filings filled the window with its higher-confidence duplicates and the lower-confidence period series never reached the reply (Bajaj's quarterly GNPA, KEC's order intake trend returned only old annual rows). **`pilot3_search`** takes `period` (Q1FY27 / FY26), `date_from`+`date_to` (filing window) and `doc_type`; it fetches the OR and AND FTS candidates (bm25), normalises bm25 inside the OR set (best = 1.0, the rest keep their ratio) and adds +0.20 for a page carrying every query word, +0.35 for a filing inside the window, +0.35 for a page that prints the period and +0.20 for the document type named. The `period` argument is normalised through `norm_period`, so the reply echoes a canonical label (FY27, Q3FY26) and a label can never be prefixed twice; a matching page under a document with no filing date no longer raises `IndexError` in the ranker (it reads the page's `known_at` as well). **`pilot3_statements`** takes `period`, `rank_terms` (the question's own words) and `latest`; `topic` now ranks the tagged statements first instead of filtering (the sentence that answers "what did they say about margins" is often tagged `nim` or `other`), `topic_matched` says whether any returned statement carried the tag, and the order is topic, period, how many of `rank_terms` the statement carries, then newest call and sequence. When no stored statement carries the topic, it searches the calls' own `doc_page` text (bm25, newest call first, the date window and `latest` respected) and returns those rows with `fallback: "doc_page_bm25"` and provenance table `doc_page` (4 Nov 2026). Tests: `plugins/reality-data/tests/test_lookups_pilot3.py` (20 tests: 19 pass; its one MCP stdio test cannot run in a sandbox that blocks named pipes; the fixture `doc_page` insert carries the T-052 `ocr_conf` column).
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
- Test: `reality_engine/tests/test_pilot3_answer_check.py` (25 tests on the fixture pilot3 database and fixture sandbox: one question per class, plus a growth whose oracle cites two revenues while the reply returns the growth %, a share over two cited order books, the `terms` fallback for a topic the tagger never emits, the results-date rule, the 31 March holiday price query, the keyword/date-window builder and the quarter-inside-year text rule). With `plugins/reality-data/tests/test_lookups_pilot3.py` (22 tests: 21 pass, the MCP stdio one skips only inside a sandbox that blocks child-process pipes) the acceptance command `python -m pytest plugins/reality-data/tests reality_engine/tests -q -k "pilot3 or lookups"` selects the pilot3 and lookup suites (195 tests on 4 Nov 2026). `reality_engine/tests/test_pilot3_kpi.py` has 28 tests (transcript source, composite titles, OCR name slips, call-period forms). The reality-data MCP must be restarted (`/mcp`) for a session to see the nine `pilot3_*` tools.

### O6. pilot3 guidance extractor and `pilot3_guidance` (T-049, 4 Nov 2026)

The MCP-only answer run's hand-read grade found the same hole in 10 of 17 wrong answers: the call or deck text that holds the guidance is in `doc_page`, but `pilot3_statements` / `pilot3_search` did not surface it, so the answerer said "no guidance given". `reality_engine/pilot3/guidance.py` (new; no model, no OCR, no network) closes it with a table of forward targets and a tool that answers them directly.

```bash
python -m reality_engine.pilot3.guidance --out <db> [--symbols KEC,BAJFINANCE,HINDALCO] [--limit-docs N]   # ~7 s on the 3 Nov db
python -m reality_engine.pilot3.guidance --out <db> --sample 40 --seed 7                                   # hand check: N random rows with their sentence
python -m reality_engine.pilot3.build --out <db> --part guidance                                          # in --part all after extract
python -m pytest reality_engine/tests/test_pilot3_guidance.py -q                                          # 22 tests
```

- **Table** `guidance` (DDL in `schema.py`, indexes `ix_gd` on symbol+metric+period and `ix_gd2` on symbol+said_on): `id`, `symbol`, `isin`, `metric`, `target_period`, `low`, `high`, `unit`, `direction` (up/down/flat), `said_on` (the filing date), `doc_key` (the ticket's `doc_id`; the column is named like every other pilot3 table), `page`, `quote` (the exact sentence), `speaker` (a transcript), `known_at`, `known_at_source`, `revision_of`, `extractor_rule`. One row per target per date: a target restated on a later call has its own `said_on` (that is what `revision_of` links), while the BSE/NSE copies and the several pages of one document collapse onto one row — the run key is `(symbol, metric, target_period, low, high, unit, said_on)` and the first document in `known_at` order supplies the page and the earliest knowledge.
- **Input.** The database's own `doc_page` for transcripts, decks, results files and press releases (annual reports and announcements are not read: they are backward-looking and would swamp precision). Transcripts are read through `transcript_statement`, so only management sentences are stored (analysts and the moderator are already excluded), with the tested speaker, role and `call_period`; decks/results/press releases are split into sentences (a bullet marker `▪•❑●` starts a new one) and keep the exact page slice. A sentence over 400 characters is a table or chart blob, not a sentence, and is skipped.
- **A sentence is stored only when it has all four of:** a number (percent range `12% to 15%` / `8-8.5%`, basis-point range, currency range `INR20 crores, INR25 crores` (only next to maybe/around/between/another), single value, or `$250 a ton`); a guidance cue (`guidance|guided|corridor|target|estimate|expect|anticipate|should be|would be|will be|going to|going forward|outlook|talking about`) in the sentence -- or, for a range only, in the 300 characters before it, which is where the analyst's question ("what is the guidance on revenue, EBITDA and order intake?") sits; a metric word in the sentence or within about 300 characters before / 150 after; and a target period. The number taken is the first numeric candidate after the nearest cue, so "costs went up 5% Q1 to Q4 ... expecting another 5%, 6%" takes the forward pair, not the measurement. A metric word inside the sentence must be within 150 characters before the number (or 40 after) -- that is what rejects a chart's tick labels; a metric word only in the question may be further away. A sentence with more than five numbers is a chart axis or a table line, not a sentence, and is skipped (`chart_blob`).
- **The metric must be the target's subject** (`subject_ok`, T-049 review 4 Nov 2026).  The hand check found a net-debt sentence stored as an interest-cost target and a share of supply as an EBITDA-margin target, both because the metric came from the question and any plausible number from the answer.  Now: (a) a share of a total ("60% of our supply", "25% of turnover", "13% share") is never a margin, a level or a rate, only `other`; (b) a percent change is not a percent level ("a 10% reduction in the interest cost" is not interest cost 10%), and no non-growth metric takes a number the sentence itself calls a growth ("we grow at 15%" is not a 15% margin) -- the growth metrics are the one class where the rate is the target; (c) when the sentence names a metric, the chosen metric must be one of them; (d) when it names none (an answer to "what about the interest cost?"), the sentence must itself be a forward statement, the question before it must name the metric, and the number must not have another subject of its own (net debt, borrowings, order book, turnover, supply, cost, a run rate) on either side.  A past measurement that used to leak (`already at`, `had estimated`, `we did`, `they had`, `run rate`) is now a past marker.
- **Metrics** are the ticket's twelve, in this priority: `nim`, `credit_cost`, `aum_growth`, `ebitda_per_tonne`, `order_intake`, `project_capital_cost` (a project's whole capital cost, T-056), `project_capital_spent` (the spend so far on it, T-056 review: emitted beside the total with the period the sentence names, never read as a candidate from a sentence pattern, so it can never pass as a year's capex), `capex`, `interest_cost`, `cost_of_production`, `revenue_growth`, `ebitda_margin`, `other` (a share or structural statement ranks last whatever text it came from). BAJFINANCE's "margin"/"margins" is its NIM; a credit-cost sentence that only names GNPA/NNPA is asset quality, not credit cost; a number must be plausible for the metric and unit (a 70-75% "margin" is a share of PBT, a 20% interest cost in Brazil is a market rate, a margin above 50% is rejected).
- **Periods.** Explicit `QnFYyy`, `HnFYyy`, `FYyy`, `FY 2026-27`, `fiscal '27` first, in the sentence then in the question. Otherwise the document's forward year: a Q1-Q3 call/deck guides its own fiscal year, a Q4 call or Q4 results filing guides the year after (a Q4 earnings call discusses the year ahead), so KEC's 18 May 2026 "for the year" row is FY27 and its 30 Jan 2026 row is FY26. A bare "Q2" maps to the next quarter with that number after the call's own ("Q1" in a Q4 call is Q1 of the next year), and a quarter preceded by versus/from/than/against is a comparison base and skipped ("5% versus Q4" names no target quarter).
- **Precision rules, T-056 loop 3 (4 Nov 2026), a hand read of all 136 rows.** Nine wrong-row families are now filtered, each with the rule that removes it: (A) a bare quarter in a backward-looking phrase is not the target period — `PAST_Q` ("Q1 results", "Q2 performance", "in the Q3 level", `revenues`, `profit`, `sales`) and a reporting verb behind it (`PAST_VERB`) make "Q2" context, so a Q1FY27 call's "Q1 results ... guidance 1.5% to 3%" is FY27, and the explicit period label nearest the target number now wins (the sentence's own "FY26" over a "Novelis Q3FY26 Earnings" heading printed 90 characters later); (B) "next year" is the year after the document's, not the document's own — a Q2FY26 call's "next year ... INR11,000 crores" is FY27, a Q4FY26 call's "this year ... next year will be INR15,000-17,000" is FY28, "the coming financial year" said 2026-10-28 is FY28, and a period label in the question that is already over is skipped ("we were 12% to 15%" in Aug 2026 is FY27, not FY26); (C) a reported result quoted against the guided range is dropped (`GUIDED_ACTUAL`: "at 23.3% was within the range we guided", "midpoint of the guidance"; `REPORT_BASIS`: "this is how we will report"); (D) an amount spent to date is an actual, blanked before the range parser (`ACTUAL_SPEND`: "$5 billion – $2.7 billion capital expenditures spent" is not a 2.7-5.0 range); (E) a project's whole capital cost is `project_capital_cost`, one row per document, while a year's capex stays `capex`; (F) `nim`/`credit_cost` are read only for a profile company with `lender: true` and sector nbfc or bank (an insurer's growth is not NIM), a segment or business named in the company's `dimensions` before the number stays out of a company metric (`segment_subject`), and `other` needs its guidance word in the number's own clause with no other noun owning it (`other_cued`: an L1 position, an order-book exposure, gross debtors and a fire impact are not targets, "I am targeting ... INR100,000 crores" and "fixed versus variable would be roughly 50%" are); (G) a sentence that ends in a question mark is never a target (a rhetorical "..., okay?" tag excepted), and a page of a transcript whose statements are held elsewhere may only contribute a sentence whose "Name:" label is one of that document's management speakers; (H) an INR amount with no unit word in a crore-scale money metric is `inr_cr`, a running header ("KEC International Limited August 11, 2026 Page 14 of 23") is cut from the sentence, and a number that is a comparison base ("against INR5,000 crores, which we got this year", "INR2,500 crores last year") is not the target; (I) the run dedupes on `(symbol, metric, period, low, high, unit, said_on)` — the same date+values from BSE and NSE or from two pages is one row — without dropping a later date's restatement.
- **The 4 Nov review, a second hand read of all 69 rows (8 wrong, 7 rules now).**  An "impact of X on <metric>" sentence is an effect, not a level (`IMPACT_OF_ON`: "the impact of Optimum Healthcare … on operating margin will be approximately 0.7%"); a hedge is no target (`HEDGE`: "whether it will be 25 or 50 basis points, difficult to quantify"); a spend said in the perfect is past (`PAST_ONLY`: "we have been spending around INR250 crores") while "we have been talking about 8% to 8.5%" is still guidance; a place's share of a split total (`PLACE_IN`: "INR1,000 crores in Orissa and INR600 crores would be in MP") and a market's growth (`MARKET_OWNS`: "China is a large, growing market … 5-7% growth") are not the company's number; a share of a combined business is a share (`SHARE_NOUN`: "the total revenue would be 27% of a combined business"); and "remains at ~$500/t" is the actual when no guidance word comes before the number, while "the AUM growth estimates of AUM remain at 24 to 25%" keeps its row (`REMAINS_AT`, checked against the nearest cue).  The spend family D masks now has its own row: `project_capital_spent`, low = high = the amount, unit `usd_bn`/`inr_cr`, `target_period` = the period the sentence names ("end of FY26" → FY26, "end of Q1FY27" → Q1FY27, "end of Q3FY26" → Q3FY26), same quote and same dedupe key.  One leftover is reported, not settled: HINDALCO's Q2 cost-of-production 3-4% row stays because two graded checkpages entries cite that page and the fixture's 145 baseline needs both.
- **Kept out:** macro forecasts (GDP, inflation, IMF, repo, "global", "ex-China", CY24) unless the sentence also names a company metric; past measurements (`achieved`, `stood at`, `was around`, `last year`, `grew by`, `improved by`): the number must not sit before every cue, and a sentence with a past marker needs its own explicit forward period ("last year would be 7.5%" is not a target); **a reported quarter's cost** (4 Nov 2026: `down 9% YoY`, `was impacted by ... $54 million`, `came in at $506` — a level that was measured, not guided); **the rate of a tariff or duty** (`RATE_OF`: "232 aluminium tariffs at 50%" is not a 50% margin); facts shaped with today/currently/as of/backlog/market share for `other`; a GNPA/NNPA actual near the chosen number; and a metric word that is far from every number.
- **Chain.** After a symbol's rows are written, `revisions()` links each row to the previous row of the same metric+period from an earlier document (ordered by `known_at`), so the MCP row carries `previous` (low/high/said_on/direction) and `changed`.
- **State, T-056 loop 3 on the pilot10 work copy (4 Nov 2026, all ten companies rebuilt).** **67 rows**: BAJFINANCE 6, HDFCBANK 1, HINDALCO 31 (5 of them `project_capital_spent`), HINDUNILVR 1, INFY 14, KEC 13, SBILIFE 1; ETERNAL, MARUTI and SUNPHARMA have none (ETERNAL's single row was an analyst's question, MARUTI has no transcript, SUNPHARMA's two rows were both review leftovers). `checkpages run` holds the fixture's 145 / 314 (KEC 29, BAJFINANCE 59, HINDALCO 57). The twelve targets the ticket lists are all still found: KEC revenue growth 12-15% FY27, margin 8-8.5% and 7-7.5% FY26 with the cut linked, 50% of the order book fixed/variable, the INR20-25 crore interest cut per quarter, the INR30,000 crore order-intake target; BAJ NIM moderation 10-15 bps FY27, credit cost 1.45-1.60% FY27, AUM growth 22-24% FY27; HINDALCO cost +5% Q1FY27 and +5-6% Q2FY27, downstream EBITDA $250/t FY27. INFY's Q1FY28/Q2FY28 mislabels are gone (one FY27 row per date: 1.5-3 on 28 Jul, 1-2 on 28 Oct), HINDUNILVR's "EBITDA margin at N% was within the guided range" rows are gone and only the 22.5-23.5 mid-term guidance remains. The live `reality_engine\data\pilot3\pilot3.db` still needs `--part transcripts` and `--part guidance` (plus `docs_collect --symbols KEC` in the wrapper) before sessions see this.
- **Precision before the loop-3 rules, 40 random rows of a 332-row build (seed 7, 4 Nov 2026, after the T-049 subject rules):** 28 state a forward target cleanly and 12 do not: a past measurement restated ("we laid out as we got to the $525 ... in the 4th Quarter as we have guided", "9-month revenue of 24% Y-o-Y"), a deck line that prints a total cost and a spend in one dash ("$5 billion – $3.2 billion capital expenditures spent"), a generic or conditional level ("generally, margins would be around 8% to 10%", "if it will decline it will be 5 to 7%"), a two-part guidance read as one slice ("H1 6% and H2 8% and overall 7%" stored as 6%), a share read as growth ("20% of the entire SAE"), and a bare answer with no subject in its own sentence. The loop-3 rules remove the dash line and the guided-range actuals; the ceiling is still a sentence with two quantities or a question whose metric is not the answer's; the upgrade path is a tagged sentence classifier, not wider cues.
- **MCP tool.** `pilot3_guidance(symbol, metric=None, period=None, as_of=None, limit=12)` in `lookups_pilot3.py`, registered in `server.py`: `metric` is a word (`margin` -> `ebitda_margin`), `period` goes through `norm_period` (FY27, Q2FY27), rows are newest first and every one carries the target, the quote, the speaker and provenance (document + page, `known_at`); `as_of` drops later and undated rows; a miss lists the metrics held. The server instructions route any guidance/outlook/target/corridor question to it first, and `pilot3_sql` lists the table. The live `reality_engine\data\pilot3\pilot3.db` needs `--part guidance` (or `--part all`) and an MCP restart before sessions see it.
- **Extractor limits.** Transcripts only when `transcript_statement` has the document; for a transcript whose pages built but whose statements did not, the generic sentence splitter reads the page and keeps a sentence only when its "Name:" label is one of that document's management speakers (an analyst's or journalist's words are dropped). A deck bullet that runs on without punctuation is split at the bullet marker only; chart numbers are not targets; one call can hold several rows of the same metric+period only on different dates (the chain orders them and the date key collapses the rest); the year of a Q4 call's unlabelled "for the year" is a rule, not a fact, so a Q4 call that talks about the year just ended yields the next year.
- **Tests.** `reality_engine/tests/test_pilot3_guidance.py` (22 tests: number ranges and pairs, period rules, fixture metric/period/unit/quote, past measurements and macro forecasts dropped, **reported actuals and tariff rates filtered**, the metric-is-the-subject rules and a share of a total, the revision chain, quote-on-page, `queries.guidance_rows` with `as_of`, the twelve real-database targets on a `.tmp` copy, **plus the T-056 cases: next/coming year forward, the backward-looking quarter, the nearest explicit label, a guided-range actual, `other`'s clause rule, a segment number, a comparison base, the running header, one row per metric+period+value+date with the restatement linked, the project spend beside its total, the seven review leftovers, and the restated estimate that must stay**). `reality_engine/tests/test_pilot3_speakers.py` (8 tests: the participants block and its document-label guard, the moderator's "with us today" names, bare name lines with the analysts excluded, a Q&A answer after an analyst becoming management, an unplaceable speaker counted but not stored, **a page-numbered footer becoming boilerplate and leaving the quote, and a media call with no moderator opening `qa` at its first journalist**). `plugins/reality-data/tests/test_lookups_pilot3.py` adds the tool, the revision chain, the search period normalisation (`FY26` echoes `FY26`, never `FYFY26`), the undated-document search and the statements fallback.

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
  Tests: `plugins/reality-data/tests/test_reality_data.py` (8 databases in the catalog, `schema('kpi_series', db='pilot3')`), `plugins/reality-data/tests/test_lookups_pilot3.py` (22 tests: `max_chars` default/cap/`bad_max_chars`, the consolidated default with the basis label; the MCP stdio test skips only in a sandbox that blocks child-process pipes), `reality_engine/tests/test_pilot3_ratios.py` (new, 2 tests: the FY26 row with its inputs; no row when an input is missing), `reality_engine/tests/test_pilot3_docs.py` (an order press release becomes an announcement titled by its headline), `reality_engine/tests/test_pilot3_guidance.py` (9 tests incl. the wrong-row assertion). In this DSH sandbox the `tmp_path` tests cannot run at all (pytest's `mkdir(mode=0o700)` temp root is unlistable here): the selection gives 105 passed / 22 errors from fixture setup (`test_pilot3_docs` 3, `test_pilot3_kpi` 6, `test_pilot3_ocr` 13), the 3 docs tests were run through a driver with an ordinary directory and pass, and on the controller they run as written. The live `pilot3.db` still needs `docs_collect` + `build --part registry` (order typing) and `build --part guidance` (guidance rows) plus an MCP restart before sessions see them.

### O9. Fast checks for a pilot3 extractor fix (T-049, 4 Nov 2026)

A full rebuild is eight minutes and the whole-database integration tests build it, so a fix round checks one
company and a fixed set of pages instead.

```bash
python -m pytest reality_engine/tests -q -k pilot3 -m "not slow"                          # fix round: 51 s in this sandbox (the tmp_path fixture errors are the sandbox's, see below)
python -m pytest reality_engine/tests -q                                                  # at merge, slow tests included
python -m reality_engine.pilot3.build --out .tmp/pilot3_kec.db --part kpi --symbols KEC   # one company: 125 s
python -m reality_engine.pilot3.checkpages run                                            # fixed pages: found / missing, 5.5 s
python -m reality_engine.pilot3.checkpages make                                           # regenerate the fixture and its baseline
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

`reality_engine/pilot3/profile.py` (new) turns the three-company pilot3 build into a build for any company list from one JSON file: `name`, `pages_db`, `raw_root` (with its `manifest.csv`), `out`, `window_start` and `companies` (`symbol`, `name`, `bse_code`, `isins`, `sector`, `lender`). The committed profile is `tasks/night_loop/pilot10_profile.json`; `--profile <json>` is taken by `docs_collect`, `build`, `kpi`, `transcripts` and `guidance`, and without it every command behaves exactly as before (the three pilot3 companies into `pilot3.db`, `--symbols` limiting only the extractors).

- **Company literals live in the JSON.** `profile.load` returns a `Profile` / `ProfileCompany`; `profile.company(symbol)` returns the `gap_loop` `Company` the store readers take (db_name and questions empty), `profile.is_lender(symbol)` answers from the profile's `lender` flag (without a profile, `ratios.LENDERS`, the present list), and `registry`, `stores`, `statements`, `ratios`, `kpi`, `transcripts`, `guidance`, `call_dates` and `docs_collect` read the active profile through these helpers.
- **docs_collect under a profile** reads the raw `manifest.csv` only (`status='ok'` rows; `known_at = dissem_ts`, bucket -> `doc_type`), writes the same `doc` / `doc_page` / FTS tables and makes no store lookup and no directory walk; a bucket with no document (`concall_audio_link`, `skip`), a file not on disk and a row without a dissemination time are counted, not written. `collect_manifest()` is the entry point.
- **No sandbox.** `kpi.extract_company` and `transcripts._transcript_docs` take `sandbox=None` under a profile and read `pages_db` only; the sandbox root is never joined.
- **Window.** `stores.apply_window` deletes rows dated before `window_start` from `fin_quarter_xbrl.period_end`, `fin_annual_line.period_end`, `shp_category.quarter_end`, `price_delivery.date` and `valuation_daily.date` (plus `bulk_block_deal.deal_date`, `insider_trade.intimation_date` and `index_price.date`); with a profile `compute_start` earlier than `window_start` the rows of `fin_quarter_xbrl`, `fin_annual_line` and `price_delivery` from it up to the window move to `<table>_input` (inputs only; `ratios.build_ratios` reads them through TEMP views and `stores.trim_derived` removes the derived rows before the window); no profile, no filter.
- **`--symbols` limits every part** under a profile (`profile.set_scope`), so a profile database built for one company holds one company; without a profile it still limits only the extractors. `--out` and `--pages-db` override the profile's paths.
- **MCP.** `lookups_pilot3.pilot_symbols()` takes the allowed companies from the database's `company` table when `REALITY_PILOT3_DB` is set (else the three pilot3 symbols), so `pilot3_kpi` and the rest serve a profile build with no code change.
- **Measured 4 Nov 2026.** Without a profile: `checkpages run` 145 found (29/78, 59/113, 57/123) and `build --part kpi --symbols KEC` on a copy plus the four `--ocr-db` databases reproduces 6,915 KEC `kpi_series` rows exactly (96 s). With the pilot10 profile, MARUTI: `docs_collect` 147 documents / 1,170 pages (17 s); `build` registry 0.2 s, pages 0.5 s, stores 15.5 s, kpi 11.8 s, transcripts 0.3 s, guidance 0.4 s -> `company` 1 row, `doc` 147 all dated, `fin_quarter_xbrl` 164 rows (min `period_end` 2025-12-31), `fin_annual_line` 260, `price_delivery` 516 (min 2025-10-01), `shp_category` 180, `kpi_series` 161; `transcript_statement` and `guidance` 0 because MARUTI's five `concall_transcript` filings are one-page cover letters. The full picture is blueprint section 9.
- **Loop 2 stores and ratios (T-056, 4 Nov 2026; blueprint section 9a).** `stores.py`: `BANK_TAGS` / `LIFE_TAGS` read by taxonomy marker in `_quarter_extras` (a bank's `InterestExpended`, an insurer's `GrossPremiumIncome`), `build_share_fallback` (shareholding-pattern total for a quarter end without a results share count), `build_deals`, `build_insiders`, `build_index_prices` (by ISIN; `schema.py` tables `bulk_block_deal`, `insider_trade`, `index_price`), `apply_window` / `trim_derived` (`INPUT_TABLES`). `statements.py` (profile builds only): bank / insurer annual P&L through `SECTOR_TAGS`, `Capital` + `ReservesAndSurplus` or `ShareholdersFunds` as net worth, lender `cash_and_equivalents` from the cash-flow closing cash, derived `investments` and annual `ebitda`. `ratios.py`: `_input_views`, `_split_factor` (annual EPS restated across a bonus or split), `F_COST_INCOME`, `POINT_IN_TIME` quarter-labelled copies of H1 ratios, one `dividend_per_share` per fiscal year, valuation on standalone for a company with no consolidated filing, zero dividend yield only with a filed zero cash payout. `profile.py`: optional `compute_start`, `extra_indices`. MCP: `server.py` and `catalog.py` list the three tables for `pilot3_sql`. Timings on the 10-company copy: stores 140 s, ratios 1.4 s; `--part ratios` is idempotent (identical rows). Tests: `test_pilot3_ratios.py` (7), `test_pilot3_core.py` (bank / life mapping, share fallback, deals and insiders by ISIN, index relative return, annual-line gating), `test_pilot3_profile.py` (`compute_start`, `extra_indices`).
- **Test:** `reality_engine/tests/test_pilot3_profile.py` (6 tests: committed profile, no-profile defaults, manifest -> pages -> registry/pages/kpi/transcripts/guidance with a nonexistent sandbox root, window filter, `--symbols` scoping, lookups on a `REALITY_PILOT3_DB` database).
- **Loop 3 printed comparatives (T-057, 4 Nov 2026; fix round 5 Nov 2026; blueprint section 9b).** `reality_engine/pilot3/comparatives.py` (`--part comparatives`, after `stores`, before `ratios`, in `all` only under a profile) reads each `results` PDF's **word boxes** (rotated by the page's `rotation_matrix` first) into `fin_quarter_printed`: every P&L column a quarterly table prints (current, preceding, year-ago, ytd, prior ytd, last full year), a canonical `line_item` from `reality_engine/pilot3/lexicon/results_lines.yaml`, rupees, `known_at` = `doc.known_at`, and `check_status` (`xbrl_ok` against `fin_quarter_xbrl`, `sum_ok` from the table's own identities, `repeat_ok` when a DIFFERENT filing printed the same period and value, `unchecked` = stored but never used by ratios). A page must be a P&L table: segment, ratio/margin, non-IFRS reconciliation, `Less:` and bracketed-cost pages are refused. EPS is checked with 2 units of its own printed decimals, never the table's scale. `ratios.py` then takes a quarter the XBRL window does not hold from the earliest filing that printed it, adds QoQ (`F_REV_QOQ`, `F_PAT_QOQ`), YoY from the same filing's year-ago column, TTM from one filing's printed columns decided by the table's shape (`last_fy + ytd - prior_ytd` when it prints a ytd; a Q4 table prints the year; `F_TTM_PRINTED`) when fewer than four quarters are held, and printed full years (`F_FY_PRINTED`). `pilot3_fin` falls back to the table after `fin_quarter_xbrl` (`definition` `printed_comparative`), and `pilot3_sql`/`catalog` list it.
  - **Trap.** `schema.create` DROPS every table it names, so a per-symbol rebuild must not use it: the part calls `schema.ensure` (`CREATE TABLE IF NOT EXISTS` + indexes) and then `DELETE FROM fin_quarter_printed WHERE symbol=?` (HANDOFF 4 Nov: one company's rebuild erased the other nine).
  - **Fast check.** `python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part comparatives --symbols HDFCBANK,MARUTI,KEC --out D:\RealityEngine\pilot10\scratch\w_cmp.db` takes 30-40 s; all ten take about 4 min. `--part ratios --out <copy>` (about 5 s) rebuilds every company from the merged quarters. Measured on the pilot10 copy 5 Nov 2026: 6,685 rows (fix round; 5,587 before), A1 651 -> 682 of 898, `valuation_daily.pe` days BAJFINANCE 188 (244 before the fix), ETERNAL 130 (72), HINDALCO 245, HINDUNILVR 178, INFY 8, KEC 188 (117), MARUTI 130 (6), SBILIFE 6, SUNPHARMA 246, HDFCBANK 11; `pytest reality_engine/tests/test_pilot3_comparatives.py -q` 18 passed.

## 5. Code tools: outline and typecheck (T-054, 4 Nov 2026)

Retired 4 Nov 2026 (moved to the Recycle Bin, history in `tasks/archive/code-intel_install/`): `plugins/code-intel/astindex.py`, `plugins/code-intel/ci.py`, `plugins/code-intel/server/core.py`, `plugins/code-intel/server/lsp.py`, `plugins/code-intel/server/server.py` and `reality_engine/tests/test_code_intel.py`.

`plugins/code-tools/` replaces the retired code-intel LSP. A resident `basedpyright-langserver` cost ~800 MB per worker and code-intel answered 1.5% of tool calls (423 of 28,787 over 207 runs); the two tools here run and exit, so nothing stays resident between calls.

- `outline(file)` — `plugins/code-tools/tools.py` walks one file with Python `ast` and returns every class, function and method with `name`, `kind`, `line`, `end_line`, the parent class and the first docstring line.
- `typecheck(files)` — one `basedpyright --outputjson` run with the checkout's `pyrightconfig.json` (120 s cap, the tree killed on timeout), returning `{errors: [{file, line, message}], error_count, seconds}`.

The MCP server is `plugins/code-tools/server.py` (`mcp__code-tools__outline`, `mcp__code-tools__typecheck`; `CODE_TOOLS_ROOT` sets the checkout); `plugins/code-tools/ct.py` is the CLI form the briefs name as the fallback. Wiring: `reality_engine/scripts/run_deepseek_harness.py` (`code_tools_patch` re-roots it at a worktree worker's checkout), `reality_engine/scripts/hp_worker.py` (`mcp_patch`), `.mcp.json`, `pyrightconfig.json`, `reality_engine/scripts/build_worker_context.py` (the pack's section 1) and `plugins/dsh-worker/server/core.py` (`TOOL_INSTRUCTION`); `plugins/dsh-worker/server/progress.py` counts `mcp__code-tools__*` as read-only. `plugins/dsh-worker/server/context_pack.py` now requires the `Evidence:` brief field (seven fields, `Evidence:` after `Accept:`), and `plugins/dsh-worker/server/plugin_server.py` states the seven in the `start_worker` description. The dsh profiles take the row in `tasks/dsh_profiles/code-tools.insert.yml`, replacing the old `mcp-code-intel` block. Tests: `plugins/code-tools/tests/test_code_tools.py`.

## 6. Loop checks: the night loop's frozen evals (T-055, 4 Nov 2026)

`reality_engine/night_eval/` (standard library + sqlite3, no model or network call) turns `tasks/night_loop/GOAL.md` into commands. `qset.py check <dir>` runs the line schema and Phase 1's Q1 sector fit (every `sector_fit` metric and row-need metric in that sector's list of `tasks/night_loop/questions/sector_vocab.json`, i.e. its own ids plus `universal` and `technical`), Q2 coverage (per company: each lens >= 10, orders 1st >= 40 %, 2nd >= 25 %, 3rd >= 10 %, needed document types) and Q3 (order-1 questions need >= 3 variations; two questions of the same symbol above 0.8 normalised token Jaccard are near-duplicates). `qset.py split <dir>` is the fixed split `int(sha256(qid)[:8],16) % 10 < 7` = dev, writing `dev.jsonl` beside the set and hidden to `.tmp/night_eval/hidden.jsonl` (the wrapper moves it; a hidden question is never printed). `answerable.py` scores A1 per need -- a typed-table row (symbol, period, basis, metric, `known_at <= as_of`; a need marked `new_table` names a Phase 2 table and is met only once the db holds it with a row for the symbol) or the `pilot3_search` bm25 page search called in-process (`plugins/reality-data/server/lookups_pilot3.py`, never through the MCP server) -- and lists the dev unmet needs by `table.metric` / `doc:<type>` as the next loop's work list; `--hidden` prints counts only. `guards.py` measures A3 provenance (value in quote, quote's first 80 normalised characters on the cited `doc_page`, `page_missing` counted separately) on the rows a branch added, A4 counts (XBRL disagreement of deck/release/transcript revenue-PAT-EBITDA at the total dimension, kpi periods starting after the document date, `known_at` before the filing, duplicate `doc.sha256`, rows per page above p99, margins > 100 %), A5 (the changed `build.py` parts on a COPY under `.tmp` with a `sitecustomize` that makes every socket connect raise, plus added lines under `reality_engine/pilot3/` scanned for company literals, ISINs, BSE codes, raw-data paths and hashes, plus the protected paths), A6 (the wrapper's test result, `--a6 ok`) and A7 (pages read and build seconds from `--timing`). `decide.py` prints ACCEPT only when A1-dev rises, A1-hidden and every company hold, A3 >= 98 %, A4 counts do not rise, A5 passes and A6 is green, with A7 allowed to rise <= 20 % only with an A1-dev gain of a point. `run_loop.py` launches one hidden `claude -p` session through `reality_engine/scripts/session_runner.py` (Opus, effort medium, <= 150 turns, 2 h, `--disallowedTools` Agent, the worker merge/push tools and `git push`/`git merge`) and prints exit, turns, tokens, `limited`; `audit.py` scans transcripts for reads of `hidden.jsonl` or `D:\RealityEngine\pilot3\answer_run*`. Commands and thresholds: `reality_engine/night_eval/README.md`. Tests: `reality_engine/tests/test_night_eval.py` (fixture sqlite databases, six-question sector sets and a temporary git repository under `.tmp`; `tmp_path` is denied in the dsh sandbox).

Known baseline on the 4 Nov live db (sample, `guards --limit 40`): A3 67 % with 40 cited pages absent from `doc_page` -- the annual-report rows (`fin_annual_line`, `doc_key` like `49222`) cite AR pages the pages part has not stored, so A3 on those rows cannot pass until the ARs are paged. A4 on the same db: 0 duplicate `doc.sha256`, 0 margins > 100 %, 0 periods starting after the document date, 2065 XBRL disagreements (the store carries several conflicting KPI rows per company/period) -- all comparable numbers for "not up".

### O11. pilot3 segments from the raw results XBRL (loop 2, 4 Nov 2026)
Script: `reality_engine/pilot3/xbrl_segments.py`; run it with `python -m reality_engine.pilot3.build --profile <json> --part segments --out <db>`
(`run(db_path, symbols)` returns files, rows, single-segment rows and check failures per symbol). Why: the results
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
