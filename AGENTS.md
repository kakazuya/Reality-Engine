# Reality Engine — Agent & Developer Guide

Reality Engine — Fundamental Reality Engine is a **dense-substrate, all-peers ensemble** Indian-equity intelligence platform with **continuous self-correction**. It ingests a lot of data (price, financials, concalls/PPT/Vahan/MF/RBI/Budget/PIB/YouTube) but does NOT reason over raw inside the limited LLM context window — raw is kept only as audit trail / replay source. Every signal is **quantized into a dense feature substrate**, then reasoned over by a competing ensemble of peer lenses (FF5 is one peer among many, not the trunk). Decisions are revisable continuously: the market-closed window is used to densely process/reason whatever data exists, even if incomplete — that is the stock-prediction ballgame. Multimodal ingestion (Budget/RBI/Concall audio/YouTube via yt-dlp+Whisper) and pgvector hybrid RAG feed the substrate, not the decision context directly.

---

## 1. System Architecture & Directory Map

```
btask01/
├── reality_engine/
│   ├── db/                 # PostgreSQL + pgvector + SQLite WAL (migration), FTS5, repository
│   │   ├── schema.sql      # SQLite WAL (legacy) + new PG DDL: business_model_profiles, moat_evaluations, geographic_exposure, regulatory_political_risks, raw_documents, document_chunks (VECTOR 1536), macro_events, ripple_effects (self-ref DAG)
│   │   ├── postgres_schema.sql # Fundamental Reality Engine DDL (countries, industries, companies, business_model_profiles, moat_evaluations, raw_documents, document_chunks ivfflat, macro_events, ripple_effects PN/MN/S, financial_metrics, model_explainer_rankings, lens_activation_log, pruning_decay_config)
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
│   │   ├── document_parser.py     # PDF & presentation parser with section chunking → document_chunks pgvector
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
│   │   └── hybrid_search.py       # pgvector cosine ivfflat + LanceDB + SQLite FTS5 fallback
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

---

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

---

## 3. Key Design Rules & Conventions

1. **Permanent ISIN Anchor**: All equity records, price history, and fundamentals must link to `master_companies.isin`. Tickers change, demerge, or rename; ISINs remain immutable.
2. **PostgreSQL + pgvector Primary, SQLite WAL Fallback**: Production uses PG `postgres_schema.sql` with `vector 1536 ivfflat`; local dev retains WAL `PRAGMA journal_mode = WAL` with 64 MB cache. Maintain transactional integrity. **Delivered (normalized) facts** live in `business_model_profiles` / `financial_metrics` / `model_explainer_rankings`; **raw_documents** are audit/replay only.
3. **All-Peers Ensemble (FF5 is one peer, not the trunk)**: Every perspective that explains even a tiny movement competes for weighting. Must-have lens families: (a) Factor/Statistical peers — FF5 (market, SMB, HML, RMW, CMA) + any mathematical/probabilistic lens; (b) Macro/Policy-change peer — `regulatory_political_risks`, `macro_events`, `countries`; (c) Business-quality / barriers / cashflow-machine peer — `business_model_profiles` + `moat_evaluations`; (d) Supply-chain / industry-linkage peer — `ripple_effects` fwd/back + `geographic_exposure` criticality/severity. Order-flow/behavioural lenses are deferred but plug in as additional competing peers. Cutoffs on price/volume exclude plain noise.
4. **Dense Substrate vs Raw**: Raw price/volume/financials/concalls/aux cannot be reasoned over raw (context-window bound at 1000 decisions/hr). Quantize every ingested signal into the dense substrate (`company_distilled_parameters`, `business_model_profiles`, `macro_events`, `ripple_effects`, `model_explainer_rankings`) *before* it influences a thesis. Raw is retained for provenance, re-distillation, event replay. Event nuance (% reduction, effective date, exceptions, conditional vs blanket) is quantized into the substrate, not left in prose. `pruning_engine.py` governs raw→dense promotion.
5. **Continuous Self-Correction (EOD + Event)**: Decisions are not taken when markets are closed, so reason heavily on available data then. Correction cadence = **EOD price + FII/DII + major event** (NOT intraday 99% noise). Maintain a **per-scrip learned noise floor** (volatility/liquidity adaptive), not a global hard cutoff — anything above a scrip's own floor is fair game. Each EOD/event batch re-ranks peer lenses, mutates embeddings, updates the dense substrate; reasoning is always revisable.
6. **Structural Theories Never Pruned + Per-Stock/Regime Rankings**: `STRUCTURAL_THEORY` milestones (e.g. profit-jump spotting, cheap-value traps) carry `is_structural_milestone=1`, half-life INF — permanent priors, never decayed. Model rankings are conditional, not absolute: store **per stock / sector / geography / time+conditions + investor-majority type** (promoter/FII/DII/retail) since the dominant explainer differs by who drives price. Schema: `model_explainer_rankings(stock_id, sector_id, geo_id, regime_tag, investor_majority, lens_family, p_value, explain_power, rank)` + `pruning_decay_config.is_structural_milestone`.
7. **Competitive Embedding Survival + MoE Temperature**: Embeddings compete brain-like — best explainers rise, losers decay (`explanation_weight` ↑/↓). Sparse MoE gating fires only some pathways per ask (transformer sparse activation); a **temperature** parameter controls explore (pathway mutations test alternate decision trees) vs exploit (consolidate winners). Log `lens_activation_log(temperature, fired_lenses)` for audit.
8. **Graceful Fallbacks**:
   - Vector search: pgvector `ivfflat cosine` → LanceDB → SQLite FTS5 when embeddings unavailable.
   - OCR: RapidOCR DirectML → PyMuPDF text extraction when GPU absent.
   - Market breadth: external web → local NSE Bhavcopy aggregation.
   - Aux feeds: headline browser scrape → `headless_fetcher.py` no-browser fetch when GUI blocked.
9. **Multimodal Attribution**: Every `raw_documents` record must store `source_url`, `published_date`, `fiscal_period`; `document_chunks` must retain `timestamp_start_sec/_end_sec` for audio/video diarization via `youtube_transcriber.py` `yt-dlp+Whisper`.
10. **Deterministic Agent Tools (Generalized Pydantic Lenses)**: Agent must call typed Pydantic tools for ANY lens — `MacroEventExtraction{PrimaryConsequence{second_order_effects:[RippleConsequence]}}`, `AdjacentPossibleExtraction{...}`, `VideoIntelligenceExtraction{...}` — never free-text graph/lens creation. `reality_engine/agent/schemas.py` is the contract source; `repository.py` persists transactionally.
11. **Strict Solvency Gate (Secondary)**: After ensemble ranking, filter `promoter pledge >15% OR interest_coverage <2.5× OR D/E >1.5×` before thesis synthesis.
12. **No Git Stash in Worktrees**: In Agent Manager worktree workflows, never use `git stash` across checkouts as stashes are globally shared.
13. **Trust Layer Before Substrate Reads**: Any consumer that presents substrate rows to an inference model (analysis, dossier, brief, ranking) must first exclude rows keyed in `substrate_quarantine` (test fixtures, `PHASE5_DEMO_*` seeds, `INE_AUTO*` synthetic ISINs) and exclude the `*_demo` / `seed_*_demo` tables wholesale. Quarantine never deletes source rows; it is re-materialized idempotently by `substrate_hygiene.apply()`. Degradation counts (constant features, template-less policy coverage, single-country geo splits, unconditional `regime_tag='*'` rankings) are *reported alongside* answers, never hidden — they state how much of the answer the substrate can actually support. `peer_graph.py` applies the same rule: it drops near-constant features instead of weighting them, refuses to emit neighbours when fewer than `MIN_ACTIVE_FEATURES` survive gating (recording the refusal in `company_peer_runs`), and never imputes a missing feature to zero.
