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
- `.git/hooks/commit-msg` refuses a message that names no `T-<digits>` and has no
  `No-ticket: <reason>` line. `merge_worker` puts the brief's ticket into the merge commit; it does
  not close it.

A worker brief carries `Ticket: T-014` or `No-ticket: <reason>`; a T-number absent from the main
checkout's `tasks/TASKS.md` is refused as `ticket_unknown`, and the brief then carries that one row.
The start gate is `plugins/dsh-worker/server/core.py` (the refusal and the row attached to the
brief) with its field check in `plugins/dsh-worker/server/context_pack.py`, and the tool description
in `plugins/dsh-worker/server/plugin_server.py` states the same field.
`reality_engine/scripts/context_guard.py` is the PostToolUse hook that asks Claude to write the
wrap-up at 400,000 tokens and again at 440,000 (session limit 450,000), once each per session.
