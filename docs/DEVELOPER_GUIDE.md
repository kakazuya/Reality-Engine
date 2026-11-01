# Developer guide

Moved from `AGENTS.md` on 1 Nov 2026, unchanged, so agents do not load it at every start. Parts may be stale: check against the code. Look up code with code-intel first.

## 1. System Architecture & Directory Map

```
btask01/
├── reality_engine/
│   ├── db/                 # SQLite (WAL) live databases + FTS5, repository (no PostgreSQL is installed or used)
│   │   ├── schema.sql      # SQLite DDL (live): business_model_profiles, moat_evaluations, geographic_exposure, regulatory_political_risks, raw_documents, document_chunks, macro_events, ripple_effects (self-ref DAG)
│   │   ├── postgres_schema.sql # UNUSED: Postgres DDL kept for reference only; nothing runs on it (countries, industries, companies, business_model_profiles, moat_evaluations, raw_documents, document_chunks ivfflat, macro_events, ripple_effects PN/MN/S, financial_metrics, model_explainer_rankings, lens_activation_log, pruning_decay_config)
│   │   ├── delivered_filings.py  # DELIVERED (normalized) filings/price/financial facts vs raw_documents (audit/replay) separation — raw is never the decision context
│   │   └── repository.py   # Query API & atomic persistence (moat_score GENERATED, ENI, ripple CTE, model rankings, dense substrate promotion)
│   ├── ingestion/          # Multimodal feeds with yt-dlp+Whisper & layout PDF parsing
│   │   ├── master_sync.py  # NSE & BSE scrip list synchronizer (ISIN anchor)
│   │   ├── nse_client.py   # NSE Full Bhavcopy, deliverable volume, PIT insider trades
│   │   ├── bse_client.py   # BSE Bhavcopy, corporate filings, announcements
│   │   ├── fundamentals_client.py # Quarterly/annual financials & balance sheet metrics → peer_financial_metrics
│   │   ├── financially_free_client.py # Advance/decline & market breadth aggregator
│   │   ├── headless_fetcher.py # Headless (no-browser) fetch of Vahan/MF/RBI/PIB/Budget aux feeds → raw_documents (no GPU needed)
│   │   ├── telegram_client.py # Thread listener with mock/offline fallback mode
│   │   ├── youtube_transcriber.py # yt-dlp + Whisper (local) + RapidOCR DirectML diarization (budget/RBI/Concall MP4) — RX 6700 XT, no cloud
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
│   │   ├── ocr_engine.py          # RapidOCR / DirectML image & document text extractor
│   │   ├── document_parser.py     # PDF & presentation parser with section chunking → document_chunks (SQLite) + FTS5
│   │   ├── event_graph.py         # (planned — Task 15/16) Transient event-graph spawner: parse %/date/exceptions, 2nd-order fwd/back supply chain
│   │   ├── ensemble_ranker.py     # (planned — Task 15/16) Per-stock/sector/geo/time+conditions + investor-majority model_explainer_rankings
│   │   ├── eod_corrector.py       # (planned — Task 15/16) Continuous self-correction: EOD price+FII/DII+event batch, per-scrip learned noise floor
│   │   ├── substrate_hygiene.py   # Trust layer: quarantines test/demo/synthetic-ISIN rows, reports structural degradation (constant features, template-less policy coverage); owns substrate_quarantine
│   │   ├── peer_graph.py          # Analog peer graph: precomputed nearest neighbours over quantified substrate with feature-signal gating, per-pair coverage, drivers and anchor baselines; owns company_peer_graph/company_peer_features/company_peer_runs
│   │   └── structural_theories.py # (planned — Task 15/16) Abstraction for permanent priors (profit-jump spotting, cheap-value traps); concept already defined in pruning_decay_config.is_structural_milestone, not a separate module yet
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
│   ├── tests/              # Comprehensive test suite
│   ├── cli.py              # Unified CLI entry point
│   └── config.py           # Paths, PRAGMAs, API headers, and thresholds
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
Execute the test suite to verify ingestion, distillation, ensemble screening, causal reasoning, self-correction, agent synthesis, and UI contracts:
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

# Headless fetch of auxiliary feeds (Vahan/MF/RBI/PIB) without a browser
python reality_engine/cli.py fetch-headless --feeds vahan,mf,rbi,pib

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
(7 tests).

A disputed number (T-040) is not loaded unless `proto3 recheck` settled on the number the row stored; the load prints how many it kept out.

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
