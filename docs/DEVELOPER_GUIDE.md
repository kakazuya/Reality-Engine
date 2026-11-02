# Developer guide

Moved from `AGENTS.md` on 1 Nov 2026 so agents do not load it at every start; checked against the code on 2 Nov (T-045). Look up code with code-intel first.

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

### L. Watching jobs at every prompt: running, stalled, failed, unreviewed (T-044)

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
```

`status` reads `plugins/dsh-worker/runtime/jobs/*/status.json` and
`tasks/efficiency/worker_reviews.jsonl`, and only job folders whose
`status.json` changed in the last 48 hours. Lines are `RUNNING <job> <minutes>m,
<tool calls> tool calls`; `STALLED` when a running job's `worker_activity_at` is
older than 10 minutes; `ENDED BADLY ...` for failed, lost, cancelled or
lease-expired jobs with no review row; and `FINISHED, NEEDS REVIEW <job> <branch>` when a job
finished in the last 48 hours, has no review row (`id`), and neither its branch nor
its job id shows as merged (one local `git` check, skipped when nothing needs it). STALLED and
RUNNING come first whatever their age; the rest sort newest first, so the
12-line cap drops the oldest history and never a live job. A registered
non-worker process is `STALLED` when its log has not changed for 5 minutes and
`ENDED` when its `--pid` is gone; its record is `.tmp/job_watch.json`. Exit code
is 0 in every case and a corrupt record is skipped. First measured run
(2026-11-02, 284 job folders): 0.36 s wall (0.29 s in process), one running job
and eleven failed/needs-review lines. Test:
`python -m pytest reality_engine/tests/test_job_watch.py -q` (20 tests).

### M. Doc review loop and session hooks (T-045)

`reality_engine/scripts/doc_review_loop.py` reviews docs with fresh Haiku 5.5 sessions (`claude -p`, medium effort, tools Read, Grep, Glob and Edit only). The queue is `git ls-files` minus `tasks/handoff/DOC_REVIEW_PROGRESS.csv`, smallest first, so a killed run resumes. It refuses to run on `main`.

- **Size:** a batch is at most 90,000 characters and 12 files; a larger file is split across sessions. A session whose context reaches 95,000 tokens is killed and retried at half the size.
- **Guards, in code:** edits outside the batch, new files, deletions and a net cut above 40% of a file are reverted. Rulings, the bank and its source files, the archive and the tracker are never sent; `tasks/ar_study/text/` is recorded as generated, unread.
- **Stops:** usage limit sleeps 15 minutes; 3 failures in a row, or $25 estimated at list price, stops it. The log's last line starts `DONE`, `STOPPED` or `PAUSED`. The estimate leaves out sessions killed at the context limit, which report no cost.
- **Overnight:** `reality_engine/scripts/doc_review_keeper.py` restarts the loop 20 minutes after a failure or crash, at most 12 times, with no model call. Done, the budget stop and a file too large for a batch end it, with a `KEEPER ended` line in the log. Each restart counts its $25 afresh.
- **Blind spot:** the reader sees a worktree with no gitignored files and cannot read the archive, `.tmp` or the dsh runtime folder. The first run wrote false "not in the repo" notes from this, so the prompt now forbids that claim; check any such note against the main checkout before merging.
- **Archive:** `--archive` reviews only `tasks/archive/`, with Read, Grep and Glob and no Edit: archived records are history, so each file is kept or proposed for deletion. Shivam lifted the archive read rule for T-045 on 2 Nov; the loop drops it from the worktree's `.claude/settings.json` only (hidden from git with skip-worktree) and puts it back when the run ends. The rule stays on `main`. First run, 2 Nov: 78 files in 9 sessions, 56 kept, 22 finished briefs deleted after Opus checked that nothing outside the archive names them.

`reality_engine/scripts/session_hooks.py` holds two hooks. `stop` blocks one stop while `job_watch` reports a stalled job, never twice in a row and never inside the loop. `precompact` prints what a summary must keep. Tests: `python -m pytest reality_engine/tests/test_doc_review_loop.py -q`.

The stream/context runner is shared with the T-048 gap loop: `reality_engine/scripts/session_runner.py` owns `child_env`, `context_of`, `build_cmd`, `run_session` (process, stream-json parse, usage, tool calls, the 95,000-token kill) and `estimate_cost` (a killed session's cost from its tokens at Haiku 5.5 list price when no `result` event arrived); `doc_review_loop.run_batch` keeps only the doc queue and its prompt. Its tests still pass unchanged.

### N. One-company gap loop (T-048)

`reality_engine/gap_loop/` answers one company's question bank in rounds, finds why each answer failed, fills the gap by extraction from the company's own documents or by a formula on stored numbers, and answers again. KEC is the first company. Cheap models do the work and it escalates only on repeated failure. `reality_engine/gap_loop/__main__.py` is the `python -m` entry and calls `loop.main`. Sessions start through `reality_engine/scripts/session_runner.py` in a new console that is hidden (`hidden_console`), so the Bash and Python calls they make open no windows on this laptop; start the loop itself hidden too (`Win32_Process.Create` with `ShowWindow=0`, or `pythonw`). Each live session also keeps `C:\Users\warri\.claude\headless-sessions\<pid>.json` (model, label, a one-line description of the work from `tiers.describe`, start, last step, peak context, tool calls and the last Bash command; `Heartbeat` in the runner, removed when the session ends), which the `headless-sessions` Claude Code mod shows above the prompt and as `claude -p: N running` in the status line.

```bash
python -m reality_engine.gap_loop --sandbox D:\RealityEngine\sandbox\kec_loop --dry-run
python -m reality_engine.gap_loop --sandbox D:\RealityEngine\sandbox\kec_loop --prepare-only
python -m reality_engine.gap_loop --sandbox D:\RealityEngine\sandbox\kec_loop
python -m reality_engine.gap_loop --sandbox D:\RealityEngine\sandbox\kec_loop --ledger-summary \
    --opus-transcript <managing session .jsonl> --since <ISO time>
python -m reality_engine.gap_loop.keeper --sandbox D:\RealityEngine\sandbox\kec_loop \
    --log D:\RealityEngine\sandbox\kec_loop\logs\loop.log [--wait-pid N]
```

The dry run prints round 1's units, sizes and tiers and calls no model. A real run first executes the prepare stage (code only, no model); `--prepare-only` runs just that stage and prints its counts. Claude starts a real run after review; the loop never edits `questions\` and never writes outside the sandbox (the job_watch state file is the one exception the ticket asks for).

- **Prepare, before round 1** (`prepare.py`, code only, no model, idempotent). Raw `reality-data` replies cannot fit a 100k session, so Python does the bulk work once: every PDF under `raw\` is read page by page with `fitz` into `kec.db` `doc_text` (a page under 50 characters of text is stored `method='needs_ocr'` with empty text, OCR being a fix-stage job), an FTS5 index (`doc_text_fts`, trigger-synced) covers the text, a `docs` row per file carries `doc_key` (path under `raw\`), doc type, title, filing date and `known_at`, and KEC's rows are copied out of the read-only stores the server reads (via `reality_engine.db.readonly.connect_ro`), each copy recorded in `sources` with its source table and key. A held PDF is dated from BSE's `bse_announcements.ann` (file stem = NEWSID, else the attachment name; the sandbox's `history\` names are NEWSIDs, not attachment names), from `corporate_documents` (publication/dissemination dates only: `doc_date` is the crawl date), or from KEC's site `_manifest.json` / `_known_at.json` by sha256. A file that cannot be dated gets `known_at` NULL and cannot back an as-of answer. Every step skips what is done, and the stage appends one `tier=0` `prepare` unit to the ledger with files, pages by method, rows per table and seconds. It stops the run before any answer when more than a third of the PDFs under `raw\history` are undated.
- **Tiers.** Tier 1 is one fresh `claude -p` Haiku 5.5 session per unit (batch of at most 5 questions, `--effort medium`, stream-json, kill at 95,000 context tokens) whose strict MCP config holds no servers at all, so no `reality-data` call can fill the context; it reads `kec.db` only, with small SQL (always `LIMIT`) and FTS queries run through Bash/Python. A unit fails only on a malformed report (no valid JSON, a qid missing, a bad status or gap type) or an over-limit kill; it halves after each over-limit kill (the half left over is queued; the check then expects only the half's questions, `loop.run_unit` passes `u=current` to the accept function) and goes to tier 2 after 2 failed Haiku attempts. The prompt (`tiers.answer_prompt`) caps each command at about 20 rows and 2,000 characters. Answer and re-answer units run 4 sessions at once (`loop.PARALLEL`, threads with their own SQLite connection, WAL mode, 30 s busy timeout); fix units run one at a time so each ledger row's added rows are its own. Round 1 resumes: a restart skips questions that already have an answer row. A computed answer lists only its stated inputs in `numbers` and gives the result and formula in the sentence (`tiers.answer_prompt`); `checks.measure_family` matches whole words, since "operations" once read as a percentage. `checks.check_number` reads a currency prefix glued to digits ("INR993 crores"), plural suffixes ("Crores", "lakhs") and "80%"; a money unit passes a contract that names another money unit. `--hp-slots N` adds N answer sessions on the HP laptop (`reality_engine/gap_loop/remote.py`): before each answer stage a SQLite backup of `kec.db` is copied to `C:\RE\sandbox\kec_loop` with scp, the prompt goes over as a file and is piped into the HP's `claude -p`, and stream-json comes back over ssh; fix units stay on this laptop because they write. The HP CLI signs in from its own `CLAUDE_CODE_OAUTH_TOKEN` user variable, which Shivam set; the loop never handles a key. A fix unit's proposals are checked line by line (`loop.accept_fix`): a bad line is counted as rejected and the rest are stored, `known_at` is taken from the cited page's filing record, and the unit fails only when every proposal fails. `store.add_formula` stores list inputs as JSON text, and `loop.main` writes its `STOPPED` line with the failing source line to the log as well as stderr. Tier 2 is one fresh Sonnet 5.5 session at medium effort (`tiers.run_tier2_sonnet`, same tools and 95k kill; Shivam, 2 Nov). The older DeepSeek tier 2 (`tiers.run_tier2`, the `Manager.start_worker` function behind the dsh-worker MCP, imported from `plugins/dsh-worker/server/core.py`; a peak-hour refusal queues the unit) is kept but is no longer the default. Tier 3 writes one line per question that got no valid row to `escalations.jsonl`, with its last check reason and everything tried, and the loop moves on; the run registers its log with `job_watch add` so the managing Opus session sees it.
- **Dsh workspace limit (DeepSeek tier 2 only).** `start_worker` refuses a workspace outside the repository, so a tier-2 unit starts at the repo root with `write_scope='data'` (danger-full-access), `confirm_repo_root_write=True` and `approved_by="Shivam, 2 Nov: full permissions inside the T-048 sandbox"` so the job record says who approved that write, and a brief that pins every write to the sandbox. The dsh job record carries tool calls but no token counts, so the ledger writes `tokens: null` with a note instead of guessing.
- **Checks, in code, before a row is stored or an answer counted** (`checks.py`): a number cites either a `doc_text` page or a row of the sandbox's `kec.db`. A page: the quote occurs on it; the number occurs in the quote (Indian digit grouping and crore/lakh/million words; a period before a number only disqualifies when a digit precedes it, so `Rs.1,23,456 crore` is read and `1.56` is not split); `known_at` is the page's filing date and not after the as-of date. A row (`table` + `rowid`): the loop reads that row with `store.row_lookup`, and the number, and the quote when one is given, must occur in it; the row's own `known_at` must equal the answer's and not be after the as-of date. Both need a measure, a unit that suits it (margin is a percent, order book is money, and `contracts.CONTRACTS` units are reused when a measure is named there) and a stated period. A malformed report fails the unit; a number that fails a check leaves its row stored as `unverified` with that reason, not counted as answered, and the next round fixes or re-answers it.
- **Gaps and fixes.** A `not_found`/`partial` answer carries one gap type: `text_missing`, `not_extracted`, `needs_formula`, `wrong_store` or `absent`; `unverified` is assigned by the loop, never reported by a model. Fix units are one group per gap type, at most 10 questions each, so 25 questions of one type are three units (absent is recorded, not fixed). Extraction scripts write page text straight into `doc_text` but only propose facts/formulas under `state\proposals\`; the loop checks and stores them, so a model never writes `facts`, `formulas` or `answers` directly.
- **Rounds.** Round 1 answers all 100 questions; each later round runs the fix units and then re-answers only the questions not `answered` plus the first 10 answered as a regression. At most 5 rounds, and two rounds in a row that close no gap stop it with `DONE`. A round with no re-answerable question also stops it.
- **Sandbox layout** (`D:\RealityEngine\sandbox\kec_loop\`): `questions\` (read-only bank), `raw\` (KEC PDFs), `kec.db` (`doc_text` + `doc_text_fts`, `docs`, `sources`, the copied KEC tables `ar_facts`, `deck_figures`, `results_filings`, `results_quarterly`, `concall_items`, `px_nse`, `px_bse`, `shp_index`, `announcements`, and the loop's own `facts`, `formulas`, `answers`), `state\` (`ledger.jsonl`, `mcp.json`, proposals, tier-2 unit results, scratch scripts), `logs\loop.log`, `reports\round_N.xlsx`, `escalations.jsonl` (one line per escalated question).
- **Ledger and reports.** Every unit attempt appends one row to `state\ledger.jsonl` and to the `ledger` sheet of that round's `reports\round_N.xlsx`: tier/model, times, attempt and outcome, input/cache-read/cache-creation/output/thinking tokens and cost, tool calls by name, Bash lines cut to 200 characters, method tags the loop proves from the run (`script_text`, `ocr`, `model_read` with read pages, `sql`, `formula`, `labelling`), pages by code against pages read by the model, rows added per table and files written. `cost_usd` is the session's own `result` event `total_cost_usd`; when the session is killed before that event, the cost is estimated from its token counts at Haiku 5.5 list price (`session_runner.estimate_cost`, from the repo's `tasks/kilo_model_pricing_2026-10-12.csv` row: $0.10/M in, $0.50/M out, cache read 0.1x and cache write 1.25x the input price) and the row carries `cost_estimated: true`. `--ledger-summary` totals these per tier and method and gives tokens per question answered; `--opus-transcript` with `--since` adds the managing session's usage blocks so the summary spans all three tiers.
- **Stops and guards.** `$15` estimated Haiku list price per run, 15-minute usage-limit sleep (Sonnet tier-2 sessions count toward the same estimate), no network fetch and no paid embedding, never `D:\Shivam_Private` or a key file, never a write outside the sandbox. The run refuses to answer when the prepare stage leaves more than a third of the `raw\history` PDFs undated. The keeper restarts the loop 20 minutes after a crash at most 12 times. Log lines end with `DONE`, `STOPPED <reason>` or `PAUSED`. Tests, no model call: `python -m pytest reality_engine/tests/test_gap_loop.py reality_engine/tests/test_doc_review_loop.py -q`.

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
flags, code-intel calls, outcome, finish-to-merge hours); `Chain of command` (per day,
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
