# Implementation Plan: Fundamental Reality Engine — Dense Substrate + All-Peers Ensemble + Continuous Self-Correction

## Overview
Build the Fundamental Reality Engine on a **dense substrate** (every ingested signal quantized into queryable tables *before* it influences a thesis) rather than reasoning over raw price/volume/concall/aux inside the LLM context window. Raw is retained only as audit trail / replay source. The market-closed window densely processes whatever data exists, even if incomplete. Screening is an **all-peers weighted ensemble**: FF5 is one peer among many, not the trunk. Every mathematical / financial / probabilistic / behavioural lens (macro-policy, business-quality, supply-chain, factor) competes for weight; plain noise is excluded by a **per-scrip learned noise floor**, not a global cutoff. Decisions are corrected **continuously** on EOD price + FII/DII + major event batches (NOT intraday 99% noise). Structural theories are **never pruned** (`is_structural_milestone=1`, half-life INF). Model rankings are per stock / sector / geography / time+conditions + investor-majority (promoter/FII/DII/retail). A **MoE temperature** gates explore/exploit with sparse pathway firing; embeddings survive competitively (best explainers rise, losers decay). Transient event-graphs are spawned on-demand (e.g. US textile tariff removal) and quantize new reality 2nd-order fwd/back.

## Architecture Decisions
- **PG primary + SQLite WAL fallback** `reality_engine/db/postgres_schema.sql` is source of truth; SQLite WAL stays for local dev. Dense substrate tables (`business_model_profiles`, `financial_metrics`, `macro_events`, `ripple_effects`, `model_explainer_rankings`) are the decision context; `raw_documents` are audit/replay only.
- **Local GPU only for vision/OCR** `reality_engine/processing/vision_engine.py` RapidOCR DirectML on RX 6700 XT, not cloud. Fallback PyMuPDF / Whisper local per `AGENTS.md:5`.
- **Vertical slicing by peer-ensemble stage**, each task delivers one queryable ensemble layer end-to-end (schema→repo→seed→screen) — keeps DB performant and testable.
- **Distill-before-delete** `distillation_pruner.py` stores moat/quality deltas before `prune_decayed_signals()` purges vectors.
- **Per-scrip learned noise floor** `eod_corrector.py` maintains `noise_floor` per `company_id` (vol/liquidity adaptive); ensemble cutoffs use it, not a global hard threshold, to exclude plain noise while keeping real moves.
- **Investor-majority rankings** `ensemble_ranker.py` persists `model_explainer_rankings(stock_id, sector_id, geo_id, regime_tag, investor_majority, lens_family, p_value, explain_power, rank)` — which model best explains which stock when, conditioned on who drives price.
- **MoE temperature gating** `orchestrator.py` + `lens_activation_log(temperature, fired_lenses)` — each run fires a sparse subset of lenses; temperature explores alternate decision trees vs exploits consolidated winners (brain-like competitive survival).
- **Transient event-graph spawning (not static ripple only)** `event_graph.py` parses %, effective date, exceptions, conditional clauses, spawns 2nd-order fwd/back supply-chain graph on demand; static `ripple_effects` DAG remains the canonical causal store.
- **Competitive embedding pruning** `pruning_engine.py` raises `explanation_weight` on surviving explainers, decays losers; `structural_theories.py` milestones carry half-life INF and are exempt from all decay.

## Dependency Graph
```
raw_documents → document_chunks (VECTOR 1536) → DENSE SUBSTRATE promotion
  ├─ business_model_profiles / moat_evaluations        (BUSINESS-QUALITY peer)
  ├─ regulatory_political_risks (GEN ENI) / macro_events (MACRO-POLICY peer)
  ├─ geographic_exposure (criticality/severity) + ripple_effects (SUPPLY-CHAIN peer)
  ├─ financial_metrics (FF5 factor peer: market/SMB/HML/RMW/CMA + technical_engine)
  └─ model_explainer_rankings (conditioning on investor-majority)
        │
        ▼  ALL-PEERS ENSEMBLE (composite_screener weighted, not top-down trunk)
  peer ensemble (FF5 / quality / policy / supply) ──▶ ensemble_ranker (MoE temp, fired_lenses log)
        │                                                    │
        │                                          structural_theories (NEVER-PRUNED branch, T½ INF)
        ▼                                                    ▼
  eod_corrector (EOD price+FII/DII+event batch) ──▶ re-rank lenses, mutate embeddings, update substrate
        │
        ▼  TRANSIENT EVENT-GRAPH (on-demand spawn)
  event_graph (parse %/date/exceptions → 2nd-order fwd/back supply chain) ──▶ quantize new reality
```

## Task List (Vertical Slices by Peer-Ensemble Stage)

### Phase 1: Foundation — PG & Master Hierarchy
- [ ] Task 1: Provision PG+pgvector & apply DDL (countries, industries, companies, dense substrate tables)
- [ ] Task 2: Seed countries (IND stability/rule-of-law) + industries with secular_growth_score + ontologies
- [ ] Task 3: Migrate master_companies (NSE/BSE ISIN anchor) into PG + verify dual-write SQLite→PG
#### Checkpoint: Foundation
- [ ] `psql -c "\d companies"` shows hierarchy + `model_explainer_rankings` present; `pytest test_master_sync` green; no ISIN drift vs SQLite.

### Phase 2: Competing Peers — Business Quality, Policy, Supply Linkage
- [ ] Task 4: Business-quality peer — `business_model_profiles` archetype/recurrence/pricing_power + `moat_evaluations` Moat=0.25SC+0.25NE+0.20CA+0.20IA+0.10ES (barriers/cashflow-machine lens)
- [ ] Task 5: Macro-policy peer — `policy_engine.py` ENI=Severity(±5)×Prob → `regulatory_political_risks.net_impact_score` GEN + `macro_events`
- [ ] Task 6: Supply-chain peer — `geographic_exposure` criticality/severity + `ripple_effects` DAG (severity/criticality dependency lens, competes with quality/policy)
#### Checkpoint: Competing Peers
- [ ] Each peer independently queryable; `v_wide_moat_candidates`, `v_policy_adjusted_screen`, supply-exposure view return deterministic scores; peers de-correlated enough to compete.

### Phase 3: All-Peers Ensemble + FF5 Factor Peer
- [ ] Task 7: FF5 factor peer — `fundamental_engine.py` + `technical_engine.py` extract market/SMB/HML/RMW/CMA + RSI/delivery-spike; store as competing peer (not just ROIC secondary)
- [ ] Task 8: All-peers `composite_screener.py` weighted ensemble ranker (FF5 + quality + policy + supply) with per-scrip learned noise floor cutoffs
- [ ] Task 9: Recursive CTE ripple verification (PN=∏Pi, MN=Raw×PN×β, S=|MN|×20/(1+ln(1+Lag))) as supply-chain transmission on steel duty case
#### Checkpoint: Ensemble
- [ ] `screen --universe nifty200 --top 20 --ensemble` returns weighted blend (not top-down); factor peer contributes measurable weight; ripple math verified.

### Phase 4: Multimodal Ingestion → Dense Substrate
- [ ] Task 10: `raw_documents`/`document_chunks` ingest (pdf_ingestor Marker + youtube_transcriber yt-dlp→Whisper local) → dense substrate promotion
- [ ] Task 11: `headless_fetcher.py` no-browser fetch of Vahan/MF/RBI/PIB/Budget aux feeds → `raw_documents` (GPU-free path)
- [ ] Task 12: pgvector hybrid search cutover (ivfflat cosine 1536 + partitioning q1..q4 → LanceDB→FTS5 fallback)
#### Checkpoint: Ingestion
- [ ] Budget/RBI/Vahan/MF ingested via headless path; POLYPLEX PPT yields visual artifacts; hybrid search returns slide footnote with correct lag.

### Phase 5: Lifecycle — Competitive Survival + Never-Prune Structural
- [ ] Task 13: `pruning_engine.py` competitive embedding survival (`explanation_weight` ↑/↓) + decay λ; `structural_theories.py` milestones `is_structural_milestone=1` T½ INF exempt
- [ ] Task 14: Distillation before deletion — monthly batch → dense substrate UPDATE (moat/quality deltas) → purge vectors, log `distillation_runs`
#### Checkpoint: Lifecycle
- [ ] `CALL prune_decayed_signals()` decays losers, retains Structural Milestone text; no orphan ripple leaves PN<0.08; distillation delta applied before purge.

### Phase 6: MoE Ranker + Transient Event-Graph + EOD Corrector
- [ ] Task 15: `ensemble_ranker.py` MoE gating with temperature + `lens_activation_log`; `model_explainer_rankings` per stock/sector/geo/time+conditions + investor-majority (promoter/FII/DII/retail)
- [ ] Task 16: `event_graph.py` transient spawner (US textile tariff: parse %/date/exceptions/conditional → 2nd-order fwd/back) + `eod_corrector.py` continuous self-correction (EOD price+FII/DII+event) + orchestrator synthesis (writer JSON/MD/HTML)
#### Checkpoint: Complete
- [ ] `rank-models --symbol HAL --investor-majority FII` queryable; `spawn-event-graph --event US_TARIFF_TEXTILE_RELIEF` correct 2nd-order graph; `correct-eod --universe nifty200` re-ranks; `test_agent_and_reporting` passes.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| PG migration breaks existing SQLite pipeline (40 filings indexed) | High | Dual-write + fallback SQLite WAL; tasks 1-3 verify no loss |
| Moat/quality/policy/supply peers correlated (ensemble degenerates to one) | High | De-correlation check at Task 8 checkpoint; weight floors per lens family |
| Per-scrip noise floor mislearned (cuts real moves or keeps noise) | Med | EOD batch backtest vs realised vol; floor clamped; Task 15 verification |
| MoE temperature mistuned (under/over explore) | Med | `lens_activation_log` audit; A/B vs stable temp; Task 15 gate |
| Vector bloat (embeddings RAM) | High | Partitioned table + competitive pruning + distill-before-delete Task 13-14 |
| Transient event-graph parse error (%/date/exceptions) | Med | Pydantic `AdjacentPossibleExtraction` enforced; steel/US-tariff case tests Task 16 |
| Investor-majority rankings sparse (retail data thin) | Med | Fallback to promoter/FII/DII; flag low-confidence ranks |

## Open Questions
- Ensemble weighting scheme: fixed heuristic vs learned per-regime weights — how to bootstrap before enough EOD correction batches?
- Per-scrip noise-floor learning params: lookback window, vol percentile, liquidity floor — shared default or per-sector?
- MoE temperature schedule: fixed vs annealed per market regime; what is the explore budget per run?
- Investor-majority data sources: which FII/DII/retail proxies are reliably available for `model_explainer_rankings`?
- Transient event-graph sourcing: auto-parse from `raw_documents` headlines vs manual event seed — trust threshold?
- Embedding model lock: `bge-m3` (LanceDB) vs `text-embedding-3-large` (pgvector 1536) — unify for competitive survival?
