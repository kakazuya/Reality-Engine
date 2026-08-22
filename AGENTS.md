# Reality Engine — Agent & Developer Guide

Reality Engine is an Indian-equity intelligence platform combining bottom-up market microstructure data, quantitative factor screening, forensic solvency validation, dynamic corporate distillation, causal macro knowledge graphs, and LLM agent orchestration.

---

## 1. System Architecture & Directory Map

```
btask01/
├── reality_engine/
│   ├── db/                 # SQLite WAL schema, indexes, FTS5 virtual tables, repository layer
│   │   ├── schema.py       # Table definitions, triggers, and migrations
│   │   └── repository.py   # Query API & atomic persistence helpers
│   ├── ingestion/          # Data feeds with resilient parsing & offline fallbacks
│   │   ├── master_sync.py  # NSE & BSE scrip list synchronizer (ISIN anchor)
│   │   ├── nse_client.py   # NSE Full Bhavcopy, deliverable volume, PIT insider trades
│   │   ├── bse_client.py   # BSE Bhavcopy, corporate filings, announcements
│   │   ├── fundamentals_client.py # Quarterly/annual financials & balance sheet metrics
│   │   ├── financially_free_client.py # Advance/decline & market breadth aggregator
│   │   └── telegram_client.py # Thread listener with mock/offline fallback mode
│   ├── processing/         # Analytics, quantitative screening, and causal reasoning
│   │   ├── technical_engine.py    # Rolling SMAs, RSI(14), delivery spike ratios
│   │   ├── fundamental_engine.py  # YoY/QoQ revenue & PAT acceleration scores
│   │   ├── composite_screener.py  # Multi-factor ranker & strict solvency gating
│   │   ├── distillation_engine.py # EAV + JSON business cyclicality & supply chain parameters
│   │   ├── causal_engine.py       # Recursive multi-hop causal graph traversal
│   │   ├── macro_simulator.py     # Macro policy shock propagation & impact matrix
│   │   ├── ocr_engine.py          # RapidOCR / DirectML image & document text extractor
│   │   └── document_parser.py     # PDF & presentation parser with section chunking
│   ├── pipeline/           # End-to-end operational pipelines
│   │   ├── phase1_runner.py       # Ingestion, computation, and checkpoint audit runner
│   │   ├── backfill.py            # Historical Bhavcopy session backfiller
│   │   ├── panic_monitor.py       # Market drawdown & crisis bargain absorption scanner
│   │   └── inbox_runner.py        # Local inbox PDF/image scanning & indexing
│   ├── search/             # Hybrid lexical & vector retrieval
│   │   └── hybrid_search.py       # LanceDB dense vector embeddings + SQLite FTS5 fallback
│   ├── agent/              # High-context AI agent orchestration & deterministic tools
│   │   ├── schemas.py             # Pydantic structured data contracts
│   │   ├── tools.py               # Deterministic quantitative & causal tools
│   │   └── orchestrator.py        # Multi-thesis daily alpha synthesizer
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
2. **SQLite WAL Persistence**: Database operations use WAL mode (`PRAGMA journal_mode = WAL;`) with 64 MB memory cache and busy timeout. Maintain transactional integrity.
3. **Graceful Fallbacks**:
   - Vector search falls back from LanceDB to SQLite FTS5 when embeddings are unavailable.
   - OCR falls back to PyMuPDF text extraction when GPU/RapidOCR is absent.
   - Market breadth falls back to local NSE Bhavcopy aggregation when external web services are unavailable.
4. **Strict Solvency Gate**: Stocks with promoter pledge $> 15\%$, interest coverage $< 2.5\times$, or debt-to-equity $> 1.5\times$ must be filtered out before thesis synthesis.
5. **Deterministic Agent Tools**: Agent orchestrators must rely on typed Pydantic tools (`reality_engine/agent/tools.py`) rather than unconstrained free-text generation.
6. **No Git Stash in Worktrees**: In Agent Manager worktree workflows, never use `git stash` across checkouts as stashes are globally shared.
