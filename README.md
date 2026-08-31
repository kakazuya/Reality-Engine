# Fundamental Reality Engine — Dense-Substrate, All-Peers Ensemble with Continuous Self-Correction

A **dense-substrate, all-peers ensemble** intelligence platform for Indian equities (NSE & BSE). It ingests a lot of raw data (price, financials, concalls/PPT, Vahan/MF/RBI/Budget/PIB/YouTube) but does **NOT** reason over raw inside the limited LLM context window — raw is retained only as audit trail / replay source. Every signal is **quantized into a dense feature substrate**, then reasoned over by a competing ensemble of peer lenses. FF5 is **one peer among many**, not the trunk. Decisions are revisable continuously via an EOD + event-driven self-correction loop, and structural theories are permanent priors that are never pruned.

**Primary Funnel (All-Peers Ensemble — not top-down-only):**
`Dense Substrate (quantized facts + raw→dense distillation) → Peer Ensemble (FF5 factor + Macro/Policy + Business-quality/Moat + Supply-chain/linkage lenses competing) → Transient Event-Graph (forward/backward 2nd-order supply chain) → MoE Ranker (sparse gating + temperature explore/exploit) → Continuous Correction Loop (EOD price + FII/DII + event, per-scrip learned noise floor)`

- Quant formulas still apply within their peer lens: `Moat = 0.25*SC+0.25*NE+0.20*CA+0.20*IA+0.10*ES (0-5)`; `ENI = Severity(±5)×Prob(0-1)`; ripple DAG `PN=∏Pi, MN=RawN×PN×β, S=|MN|×20/(1+ln(1+Lag))`.
- The old top-down funnel (Industry → Moat → Policy → ROIC) is **one possible lens configuration**, demoted to a peer among many — not the sole path.
- Model rankings are conditional: stored per stock / sector / geography / time+conditions + investor-majority type (promoter/FII/DII/retail).

---

## 📚 Master Architecture & Documentation Suite

This system is comprehensively documented across modular specification files:

- **[`00_SYSTEM_OVERVIEW.md`](./00_SYSTEM_OVERVIEW.md)**: Master architecture, core market reality objective, counsel of subagents, and hardware VRAM/RAM allocation budgets.
- **[`01_DATA_INGESTION_PIPELINE.md`](./01_DATA_INGESTION_PIPELINE.md)**: Ingestion mechanisms for NSE Full Bhavcopy & Delivery (`sec_bhavdata_full.csv`), BSE Corporate Filings/XBRL, Telegram Forum Threads, FinanciallyFree Scraper, and headless (no-browser) Vahan/MF/RBI/PIB/Budget feeds.
- **[`02_PROCESSING_OCR_AND_VECTORS.md`](./02_PROCESSING_OCR_AND_VECTORS.md)**: GPU-accelerated RapidOCR (DirectML/ONNX on AMD RX 6700 XT), PDF Concall parsing with PyMuPDF, and LanceDB dense vector embeddings with `BAAI/bge-m3`.
- **[`03_STORAGE_AND_DATABASE_SCHEMA.md`](./03_STORAGE_AND_DATABASE_SCHEMA.md)**: Complete PostgreSQL + pgvector schema (with SQLite WAL fallback), FTS5, delivered-filings vs raw-documents separation, `model_explainer_rankings`, `pruning_decay_config`, and retention policies.
- **[`04_QUANT_SCREENING_AND_FACTOR_MODEL.md`](./04_QUANT_SCREENING_AND_FACTOR_MODEL.md)**: Mathematical formulas for Delivery Spike Ratio, Delivery Conviction, Trend Filters, YoY Earnings Acceleration, FF5 factor baseline, and all-peers composite screener.
- **[`05_CLOUD_AI_AGENT_AND_TOOL_CALLING.md`](./05_CLOUD_AI_AGENT_AND_TOOL_CALLING.md)**: High-Context LLM Agent architecture, generalized causal/macro/event-graph Pydantic tool schemas, system prompts, and MoE temperature gating.
- **[`06_EXECUTION_ROADMAP_AND_VERIFICATION.md`](./06_EXECUTION_ROADMAP_AND_VERIFICATION.md)**: Step-by-step phased execution plan, exit verification gates, and failure recovery runbooks.
- **[`07_DYNAMIC_FINANCIAL_DISTILLATION_ENGINE.md`](./07_DYNAMIC_FINANCIAL_DISTILLATION_ENGINE.md)**: Dynamic parameter engine, EAV + JSON schema, sector cyclicality ontologies, revenue sensitivities, supply chain nodes, and frontier knowledge distillation (raw→dense).
- **[`08_MACRO_POLICY_AND_CAUSAL_KNOWLEDGE_GRAPH.md`](./08_MACRO_POLICY_AND_CAUSAL_KNOWLEDGE_GRAPH.md)**: Macro policy feeds (Union Budget, RBI Surveys, Research Reports), recursive causal graph schema, and multi-hop transmission walks.
- **[`09_CRITICAL_REFINEMENTS_AND_ADVERSARIAL_AUDIT.md`](./09_CRITICAL_REFINEMENTS_AND_ADVERSARIAL_AUDIT.md)**: Adversarial subagent stress tests, subtractions (eliminating brittle web scraping), and critical additions (SEBI Insider Trading, Bulk/Block deals, Forensic Solvency gates, Panic Triggers, per-scrip noise floor).
- **[`FUNDAMENTAL_REALITY_ENGINE_OBJECTIVES.md`](./FUNDAMENTAL_REALITY_ENGINE_OBJECTIVES.md)**: Locked revised vision — dense substrate (§1), all-peers ensemble (§2), self-correction (§3), transient event-graph (§4), structural theories + investor-majority rankings (§5), MoE (§6).

---

## ⚡ Quick Architecture Overview

```
[ Concalls, PPTs & Corporate Filings ] ──┐
[ NSE / BSE Bhavcopy & Delivery Flow ]  ──┼──> [ RAW TIER: raw_documents / document_chunks / price+FII-DII ]
[ Telegram Channels + GPU OCR ]        ──┤                     │  (audit trail / replay only — NOT decision context)
[ Headless Vahan/MF/RBI/PIB/Budget ]   ──┘                     ▼
                                          [ DISTILLATION ENGINE ]  (quantize every signal → DENSE SUBSTRATE)
                                                 company_distilled_parameters │ business_model_profiles
                                                 macro_events │ ripple_effects │ model_explainer_rankings
                                                                │
                          ┌─────────────────────────────────────┼─────────────────────────────────────┐
                          ▼                                      ▼                                      ▼
                 [ PEER ENSEMBLE ]                    [ TRANSIENT EVENT-GRAPH ]                [ STRUCTURAL THEORIES ]
        FF5 factor │ Macro/Policy │ Moat/Q      parse %/date/exceptions → 2nd-order         (profit-jump, cheap-value
        Supply-chain/linkage lenses COMPETE        fwd/back supply chain (tariff walkthrough)  traps) NEVER pruned INF
                          │                                      │
                          └──────────────────────┬───────────────┘
                                                 ▼
                                    [ MoE RANKER ]  (sparse gating, temperature explore/exploit,
                                                     investor-majority conditioning, competitive survival)
                                                 │
                                                 ▼
                                    [ CONTINUOUS CORRECTION LOOP ]
                          (EOD price + FII/DII + event → re-rank lenses, mutate embeddings,
                           update substrate; per-scrip learned noise floor; NOT intraday 99% noise)
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

### 4. Headless Aux-Feed & Supply-Linkage Ingestion
```bash
# No-browser fetch of auxiliary macro/industry feeds into raw_documents (then distilled to substrate)
python reality_engine/cli.py fetch-headless --feeds vahan,mf,rbi,pib

# Inspect per-stock/sector/geo + investor-majority model rankings
python reality_engine/cli.py rank-models --symbol HAL --investor-majority FII

# Spawn a transient event-graph (forward/backward 2nd-order supply chain reasoning)
python reality_engine/cli.py spawn-event-graph --event US_TARIFF_TEXTILE_RELIEF --max-hops 3
```
