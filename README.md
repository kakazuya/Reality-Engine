# Bottom-Up Market Reality Model & Equity Intelligence Engine

An autonomous, multi-layer **Bottom-Up Relational Reality Model & Techno-Funda Intelligence Engine** for Indian equities (NSE & BSE).

The primary objective is to construct an interconnected, causal knowledge graph connecting **Stocks $\leftrightarrow$ Sectors $\leftrightarrow$ Supply Chains $\leftrightarrow$ Geographies $\leftrightarrow$ Macro/Geopolitical/Military Factors** through the systematic distillation of corporate concall transcripts, investor presentations, annual reports, deliverable volume flows, and alternative intelligence feeds.

This deep model provides an asymmetric informational and structural conviction edge—enabling immediate identification of mispriced, resilient companies when market panics and broad corrections occur.

---

## 📚 Master Architecture & Documentation Suite

This system is comprehensively documented across modular specification files:

- **[`00_SYSTEM_OVERVIEW.md`](./00_SYSTEM_OVERVIEW.md)**: Master architecture, core market reality objective, counsel of subagents, and hardware VRAM/RAM allocation budgets.
- **[`01_DATA_INGESTION_PIPELINE.md`](./01_DATA_INGESTION_PIPELINE.md)**: Ingestion mechanisms for NSE Full Bhavcopy & Delivery (`sec_bhavdata_full.csv`), BSE Corporate Filings/XBRL, Telegram Forum Threads, and Authenticated FinanciallyFree Scraper.
- **[`02_PROCESSING_OCR_AND_VECTORS.md`](./02_PROCESSING_OCR_AND_VECTORS.md)**: GPU-accelerated RapidOCR (DirectML/ONNX on AMD RX 6700 XT), PDF Concall parsing with PyMuPDF, and LanceDB dense vector embeddings with `BAAI/bge-m3`.
- **[`03_STORAGE_AND_DATABASE_SCHEMA.md`](./03_STORAGE_AND_DATABASE_SCHEMA.md)**: Complete SQLite 3 WAL database schema, FTS5 full-text virtual tables, dynamic EAV+JSON parameter tables, and retention policies.
- **[`04_QUANT_SCREENING_AND_FACTOR_MODEL.md`](./04_QUANT_SCREENING_AND_FACTOR_MODEL.md)**: Mathematical formulas for Delivery Spike Ratio, Delivery Conviction, Trend Filters, YoY Earnings Acceleration, and Top candidate screener.
- **[`05_CLOUD_AI_AGENT_AND_TOOL_CALLING.md`](./05_CLOUD_AI_AGENT_AND_TOOL_CALLING.md)**: Online High-Context LLM Agent architecture, causal and macro tool schemas, system prompts, and Pydantic structured output schemas.
- **[`06_EXECUTION_ROADMAP_AND_VERIFICATION.md`](./06_EXECUTION_ROADMAP_AND_VERIFICATION.md)**: Step-by-step phased execution plan, exit verification gates, and failure recovery runbooks.
- **[`07_DYNAMIC_FINANCIAL_DISTILLATION_ENGINE.md`](./07_DYNAMIC_FINANCIAL_DISTILLATION_ENGINE.md)**: Dynamic parameter engine, EAV + JSON schema, sector cyclicality ontologies, revenue sensitivities, supply chain nodes, and frontier knowledge distillation.
- **[`08_MACRO_POLICY_AND_CAUSAL_KNOWLEDGE_GRAPH.md`](./08_MACRO_POLICY_AND_CAUSAL_KNOWLEDGE_GRAPH.md)**: Macro policy feeds (Union Budget, RBI Surveys, Research Reports), recursive SQLite causal graph schema, and multi-hop transmission walks.
- **[`09_CRITICAL_REFINEMENTS_AND_ADVERSARIAL_AUDIT.md`](./09_CRITICAL_REFINEMENTS_AND_ADVERSARIAL_AUDIT.md)**: Adversarial subagent stress tests, subtractions (eliminating brittle web scraping), and critical additions (SEBI Insider Trading, Bulk/Block deals, Forensic Solvency gates, and Panic Triggers).

---

## ⚡ Quick Architecture Overview

```
[ Concalls, PPTs & Corporate Filings ] ──┐
[ NSE / BSE Bhavcopy & Delivery Flow ]  ──┼──> [ Knowledge Graph (SQLite WAL + LanceDB) ]
[ Telegram Channels + GPU OCR ]        ──┤                     │
[ FinanciallyFree Breadth Portal ]      ──┘                     ▼
                                                [ Frontier Distillation Worker ]
                                                (Maps Causal & Supply Chain Links)
                                                               │
                                                               ▼
                                                [ Cloud AI Tool-Calling Agent ]
                                                (Simulates Shocks & Crisis Value)
                                                               │
                                                               ▼
                                                [ Crisis & EOD Asymmetric Edge ]
                                                (Dispatches Deep Conviction Setups)
```

---

## 🚀 Quick Start & Environment Bootstrap

### 1. Automated Windows Bootstrap (Recommended)
Run the automated bootstrap script to create a virtual environment, install dependencies, seed knowledge ontologies, and run system verification:
```powershell
# PowerShell
.\bootstrap.ps1

# Or from Windows CMD
bootstrap.bat
```

To bootstrap without creating a separate `.venv` (using the currently active Python):
```powershell
.\bootstrap.ps1 -SkipVenv
```

To install all optional modules (OCR, LanceDB, Playwright, Telethon):
```powershell
.\bootstrap.ps1 -FullInstall
```

### 2. Manual Installation
```bash
# Install core runtime dependencies
pip install -r requirements.txt

# Seed dynamic parameter ontologies and canonical causal graph
python reality_engine/cli.py seed-ontologies

# Run test suite verification
python -m unittest discover -s reality_engine/tests -p "test_*.py"
```

### 3. Launching the Financial Terminal Dashboard
```bash
python reality_engine/cli.py dashboard
# Open http://localhost:8501 in your browser
```
