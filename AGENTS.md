# Reality Engine — Agent & Developer Guide

Reality Engine — Fundamental Reality Engine is a top-down Indian-equity intelligence platform prioritizing qualitative business moats and policy tailwinds before financial validation. It fuses macro/geopolitical stability, industry secular growth, business-model archetype & moat quantification (Moat=0.25*SC+0.25*NE+0.20*CA+0.20*IA+0.10*ES), policy Expected Net Impact (ENI=Severity×Probability), and recursive ripple DAG causal transmission (PN=∏Pi, MN=RawN×PN×β, S=|MN|×20/(1+ln(1+Lag))) with secondary ROIC>WACC / FCF validation, multimodal ingestion (Budget/RBI/Concall audio/YouTube via yt-dlp+Whisper), and pgvector hybrid RAG.

---

## 1. System Architecture & Directory Map

```
btask01/
├── reality_engine/
│   ├── db/                 # PostgreSQL + pgvector + SQLite WAL (migration), FTS5, repository
│   │   ├── schema.sql      # SQLite WAL (legacy) + new PG DDL: business_model_profiles, moat_evaluations, geographic_exposure, regulatory_political_risks, raw_documents, document_chunks (VECTOR 1536), macro_events, ripple_effects (self-ref DAG)
│   │   ├── postgres_schema.sql # Fundamental Reality Engine DDL (countries, industries, companies, business_model_profiles, moat_evaluations, raw_documents, document_chunks ivfflat, macro_events, ripple_effects PN/MN/S, financial_metrics)
│   │   └── repository.py   # Query API & atomic persistence (moat_score GENERATED, ENI, ripple CTE)
│   ├── ingestion/          # Multimodal feeds with yt-dlp+Whisper & layout PDF parsing
│   │   ├── master_sync.py  # NSE & BSE scrip list synchronizer (ISIN anchor)
│   │   ├── nse_client.py   # NSE Full Bhavcopy, deliverable volume, PIT insider trades
│   │   ├── bse_client.py   # BSE Bhavcopy, corporate filings, announcements
│   │   ├── fundamentals_client.py # Quarterly/annual financials & balance sheet metrics → peer_financial_metrics
│   │   ├── financially_free_client.py # Advance/decline & market breadth aggregator
│   │   ├── telegram_client.py # Thread listener with mock/offline fallback mode
│   │   ├── youtube_transcriber.py # yt-dlp + Whisper (local) + RapidOCR DirectML diarization (budget/RBI/Concall MP4) — RX 6700 XT, no cloud
│   │   └── pdf_ingestor.py      # Layout-aware PyMuPDF/Marker for Budget/Economic Survey
│   ├── processing/         # Analytics, moat/ripple quantification, and causal reasoning
│   │   ├── technical_engine.py    # Rolling SMAs, RSI(14), delivery spike ratios
│   │   ├── fundamental_engine.py  # YoY/QoQ revenue & PAT acceleration scores → financial_metrics
│   │   ├── composite_screener.py  # Top-down ranker: moat≥3.5 + policy score≥0 + ROIC>WACC (secondary)
│   │   ├── moat_scorer.py         # Moat=0.25*SC+0.25*NE+0.20*CA+0.20*IA+0.10*ES, width/trajectory
│   │   ├── policy_engine.py       # ENI=Severity(±5)×Prob, regulatory_political_risks aggregator
│   │   ├── distillation_engine.py # EAV + JSON business cyclicality & supply chain parameters
│   │   ├── causal_engine.py       # Recursive CTE ripple_chain: PN=∏Pi, MN=RawN×PN×β, S=|MN|×20/(1+ln(1+Lag))
│   │   ├── macro_simulator.py     # Macro policy shock propagation & impact matrix
│   │   ├── ocr_engine.py          # RapidOCR / DirectML image & document text extractor
│   │   └── document_parser.py     # PDF & presentation parser with section chunking → document_chunks pgvector
│   ├── pipeline/           # End-to-end operational pipelines
│   │   ├── phase1_runner.py       # Ingestion, computation, and checkpoint audit runner
│   │   ├── backfill.py            # Historical Bhavcopy session backfiller
│   │   ├── panic_monitor.py       # Market drawdown & crisis bargain absorption scanner
│   │   └── inbox_runner.py        # Local inbox PDF/image scanning & indexing → raw_documents
│   ├── search/             # Hybrid lexical & vector retrieval
│   │   └── hybrid_search.py       # pgvector cosine ivfflat + LanceDB + SQLite FTS5 fallback
│   ├── agent/              # High-context AI agent orchestration & deterministic tools
│   │   ├── schemas.py             # Pydantic structured data contracts (MacroEventExtraction: PrimaryConsequence/RippleConsequence recursive)
│   │   ├── tools.py               # Deterministic quantitative & causal tools (moat, ENI, ripple CTE)
│   │   └── orchestrator.py        # Top-down multi-thesis daily alpha synthesizer (Industry→Moat→Policy→ROIC)
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
Execute the test suite to verify ingestion, screening, causal reasoning, agent synthesis, and UI contracts:
```bash
# Run all unit tests
python -m unittest discover -s reality_engine/tests -p "test_*.py"

# Run a specific test module
python -m unittest reality_engine.tests.test_phase1
python -m unittest reality_engine.tests.test_quant_hardening
python -m unittest reality_engine.tests.test_agent_and_reporting
python -m unittest reality_engine.tests.test_cli_and_dashboard
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

# 4. Run full Phase 1 pipeline (Ingestion + Screening + Top 200 checkpoint)
python reality_engine/cli.py run-phase1 --days 25 --top 200 --workers 8

# 5. Audit Top 200 data completeness checkpoint
python reality_engine/cli.py verify-checkpoint
```

### C. Visual Dashboard Workflow
Launch the interactive Streamlit dashboard:
```bash
python reality_engine/cli.py dashboard --port 8501 --host localhost
# Web interface available at http://localhost:8501
```

### D. Quantitative Screening & Alpha Generation
```bash
# Screen top 20 candidates in Nifty 200
python reality_engine/cli.py screen --universe nifty200 --top 20

# Scan for panic/crisis bargain candidates (drawdown absorption)
python reality_engine/cli.py screen --crisis
python reality_engine/cli.py monitor-panic

# Synthesize daily high-conviction alpha theses and export JSON/MD/HTML reports
python reality_engine/cli.py run-daily-alpha --universe nifty200 --top 20 --top-theses 5

# Inspect full intelligence dossier for a single stock
python reality_engine/cli.py inspect-stock HAL
```

### E. Macro Causal Graph & Shock Simulation
```bash
# Trace downstream transmission walk from a macro/policy node
python reality_engine/cli.py trace-causal-chain --node UNION_BUDGET_2026_RAIL_CAPEX --max-hops 3

# Simulate shock propagation across sectors and companies
python reality_engine/cli.py simulate-macro-shock --shock COMMODITY_CRUDE_OIL --sector ALL
```

### F. Inbox Ingestion & Concall Search
```bash
# Process research reports and charts from reality_engine/data/inbox/
python reality_engine/cli.py process-inbox

# Search concall transcripts and investor presentations (hybrid lexical + vector)
python reality_engine/cli.py search-concall --query "order book capex margin guidance" --symbol TITAGARH
```

---

## 3. Key Design Rules & Conventions

1. **Permanent ISIN Anchor**: All equity records, price history, and fundamentals must link to `master_companies.isin`. Tickers change, demerge, or rename; ISINs remain immutable.
2. **PostgreSQL + pgvector Primary, SQLite WAL Fallback**: Production uses PG `postgres_schema.sql` with `vector 1536 ivfflat`; local dev retains WAL `PRAGMA journal_mode = WAL` with 64 MB cache. Maintain transactional integrity.
3. **Top-Down Funnel Priority**: `Industry secular_growth_score≥4 → Moat total_moat_score≥3.5 + trajectory Stable/Expanding → Policy agg ENI≥0 → ROIC>WACC` `reality_engine/agent/tools.py` must screen in this order; never bottom-up price-only.
4. **Quantification Rubric (PDF spec)**: `Moat = 0.25*SC+0.25*NE+0.20*CA+0.20*IA+0.10*ES (0-5)` `v_wide_moat_candidates`; `ENI = Severity(±5)×Prob(0-1)` `regulatory_political_risks.net_impact_score` GENERATED; `PN=∏Pi` `MN=RawN×PN×β` `S=|MN|×20/(1+ln(1+Lag))` `ripple_effects` recursive CTE `reality_engine/db/postgres_schema.sql:5` — log scores verbatim from extraction, not prose.
5. **Graceful Fallbacks**:
   - Vector search: pgvector `ivfflat cosine` → LanceDB → SQLite FTS5 when embeddings unavailable.
   - OCR: RapidOCR DirectML → PyMuPDF text extraction when GPU absent.
   - Market breadth: external web → local NSE Bhavcopy aggregation.
6. **Strict Solvency Gate (Secondary)**: After moat/policy, filter `promoter pledge >15% OR interest_coverage <2.5× OR D/E >1.5×` before thesis synthesis.
7. **Multimodal Attribution**: Every `raw_documents` record must store `source_url`, `published_date`, `fiscal_period`; `document_chunks` must retain `timestamp_start_sec/_end_sec` for audio/video diarization via `youtube_transcriber.py` `yt-dlp+Whisper`.
8. **Deterministic Agent Tools**: Agent must call typed Pydantic tools `MacroEventExtraction{PrimaryConsequence{second_order_effects:[RippleConsequence]}}` `reality_engine/agent/schemas.py` — never free-text graph creation.
9. **No Git Stash in Worktrees**: In Agent Manager worktree workflows, never use `git stash` across checkouts as stashes are globally shared.
