# Task List — Fundamental Reality Engine (REVISED: Dense Substrate + All-Peers Ensemble + Continuous Self-Correction)

> Reframed from the prior top-down funnel plan to the all-peers ensemble + continuous self-correction
> vision. 16 tasks preserved, re-cut by peer-ensemble stage. Foundational PG/master code from prior
> execution exists; these tasks revise/expand acceptance to the new pipeline (per-scrip noise floor,
> investor-majority rankings, MoE temperature, transient event-graph, competitive survival).

## Task 1: Provision PG+pgvector & apply DDL
**Description:** Create PG cluster, enable `vector`, run `reality_engine/db/postgres_schema.sql` (countries, industries, companies, dense substrate + `model_explainer_rankings`, `lens_activation_log`, `pruning_decay_config`). SQLite stays fallback.
**Acceptance:** `psql -c "\d companies"` + `\d model_explainer_rankings` present; `pruning_decay_config` has `is_structural_milestone` flag rows; fallback path unchanged.
**Verification:** `psql -f postgres_schema.sql` succeeds; `pytest reality_engine/tests/test_db`
**Dependencies:** None
**Files:** `reality_engine/db/postgres_schema.sql`, `reality_engine/config.py`
**Scope:** S

## Task 2: Seed countries + industries + ontologies
**Description:** Insert IND stability/rule-of-law + industries with secular_growth_score + dynamic parameter ontologies (cyclicality, supply-chain params) that feed the dense substrate.
**Acceptance:** `SELECT * FROM industries WHERE secular_growth_score>=4.0` returns curated list; ontology seed idempotent.
**Verification:** `python reality_engine/cli.py seed-ontologies`
**Dependencies:** Task 1
**Files:** `reality_engine/db/seed_fundamental.py`, `FUNDAMENTAL_REALITY_ENGINE_OBJECTIVES.md:1`
**Scope:** S

## Task 3: Migrate master_companies ISIN anchor
**Description:** Dual-write NSE/BSE master sync into PG `companies(isin, ticker)` + SQLite, verify no ticker drift. ISIN immutable anchor for all price/fundamental/ensemble records.
**Acceptance:** `COUNT(DISTINCT isin)` PG == SQLite `master_companies`; `is_active` preserved.
**Verification:** `python reality_engine/cli.py sync-master --dry-run` diff 0
**Dependencies:** Task 1
**Files:** `reality_engine/ingestion/master_sync.py`, `reality_engine/db/repository.py`
**Scope:** M

## Checkpoint: Foundation
- [ ] PG hierarchy + dense substrate tables exist, master migrated, SQLite still serving
- [ ] Tests pass: `test_phase1` master sync; `model_explainer_rankings` schema live

## Task 4: Business-quality peer (moat / barriers / cashflow)
**Description:** `business_model_profiles` archetype/recurrence/pricing_power + `moat_evaluations` Moat=0.25SC+0.25NE+0.20CA+0.20IA+0.10ES (GENERATED), width/trajectory. This is ONE competing peer (quality/barriers/cashflow-machine lens), not the trunk.
**Acceptance:** POLYPLEX SC4 NE1 CA3 IA3 ES2 → 2.75 Narrow Stable stored; `v_wide_moat_candidates` deterministic; quality peer exposes `explanation_weight` column for ensemble.
**Verification:** `SELECT total_moat_score FROM moat_evaluations` deterministic; `pytest test_quant_hardening`
**Dependencies:** Task 2,3
**Files:** `reality_engine/processing/moat_scorer.py`, `reality_engine/agent/schemas.py`
**Scope:** M

## Task 5: Macro-policy peer (ENI aggregator)
**Description:** `policy_engine.py` ENI=Severity(±5)×Prob → `regulatory_political_risks.net_impact_score` GEN + `macro_events`. Must-have peer; competes with quality/supply.
**Acceptance:** Steel duty Headwind -3.0×0.85 → -2.55 stored; `v_policy_adjusted_screen` aggregates ENI; peer weight column present.
**Verification:** `SELECT SUM(net_impact_score) GROUP BY company_id` matches manual
**Dependencies:** Task 4
**Files:** `reality_engine/processing/policy_engine.py`
**Scope:** S

## Task 6: Supply-chain peer (criticality / severity linkage)
**Description:** `geographic_exposure` criticality/severity + `ripple_effects` self-ref DAG. Must-have peer capturing supply-chain dependency (who benefits more than primary via 2nd-order fwd/back). Competes with quality/policy/FF5.
**Acceptance:** Steel duty case yields 1st→2nd→3rd severity rows; supply-exposure view queryable with criticality weights.
**Verification:** `SELECT * FROM geographic_exposure WHERE company_id=...` criticality sane
**Dependencies:** Task 5
**Files:** `reality_engine/db/postgres_schema.sql:5`, `reality_engine/processing/causal_engine.py`
**Scope:** M

## Checkpoint: Competing Peers
- [ ] Quality + policy + supply peers each independently queryable with `explanation_weight`
- [ ] De-correlation sanity: peers not >0.9 correlated on sample universe (else ensemble degenerates)
- [ ] Human spot-check of moat rubric samples

## Task 7: FF5 factor peer integration
**Description:** `fundamental_engine.py` + `technical_engine.py` extract FF5 (market/SMB/HML/RMW/CMA) + RSI(14)/delivery-spike. Stored as a competing peer — mathematically explains tiny movements, not just ROIC secondary validation.
**Acceptance:** `financial_metrics` holds FF5 loadings + factor z-scores for Top200; peer weight column present.
**Verification:** `pytest test_quant_hardening` factor extraction
**Dependencies:** Task 6
**Files:** `reality_engine/processing/fundamental_engine.py`, `reality_engine/processing/technical_engine.py`
**Scope:** M

## Task 8: All-peers ensemble ranker (composite_screener)
**Description:** Refactor `composite_screener.py` to weighted all-peers blend (FF5 + quality + policy + supply) with **per-scrip learned noise floor** cutoffs (NOT global hard threshold, NOT top-down trunk). Applies strict solvency secondary gate.
**Acceptance:** `screen --universe nifty200 --top 20 --ensemble` returns weighted blend where each lens family contributes measurable, non-zero weight; plain noise excluded by per-scrip floor.
**Verification:** `pytest test_quant_hardening` ensemble-weight assertion; factor peer weight >0
**Dependencies:** Task 4,5,6,7
**Files:** `reality_engine/processing/composite_screener.py`
**Scope:** M

## Task 9: Recursive CTE ripple (supply transmission) verification
**Description:** `causal_engine.py` ripple_chain CTE PN=∏Pi, MN=Raw×PN×β, S=|MN|×20/(1+ln(1+Lag)) as supply-chain transmission; Pydantic `MacroEventExtraction` enforced (no free-text graph).
**Acceptance:** Steel duty 1st +3.80 0m, 2nd -2.43 3m, 3rd -1.41 6m significance order verified.
**Verification:** `python reality_engine/cli.py trace-causal-chain --node TATASTEEL --max-hops 3` matches expected
**Dependencies:** Task 6
**Files:** `reality_engine/processing/causal_engine.py`
**Scope:** M

## Checkpoint: Ensemble
- [ ] Ensemble screen respects peer weights (not funnel order); factor peer contributes
- [ ] Per-scrip noise floor cutoffs applied; ripple math verified; `test_agent_and_reporting` schema pass

## Task 10: Multimodal raw_documents/document_chunks → dense substrate
**Description:** Wire `youtube_transcriber.py` yt-dlp→Whisper local + `pdf_ingestor.py` Marker → `raw_documents` → `document_chunks VECTOR 1536` → dense substrate promotion (quantize %/date/exceptions into substrate, not prose).
**Acceptance:** Budget PDF 2026 ingested → `raw_documents source_type Union_Budget` + 20 chunks with embeddings + distilled params.
**Verification:** `search-concall --query "order book"` hits pgvector then FTS5 fallback
**Dependencies:** Task 1
**Files:** `reality_engine/ingestion/youtube_transcriber.py`, `reality_engine/processing/document_parser.py`
**Scope:** L

## Task 11: Headless fetcher (Vahan/MF/RBI/PIB/Budget)
**Description:** `headless_fetcher.py` no-browser fetch of auxiliary feeds → `raw_documents` (GPU-free). Replaces GUI scrape when browser blocked; feeds dense substrate via distillation.
**Acceptance:** `fetch-headless --feeds vahan,mf,rbi,pib` populates `raw_documents` with source_url + published_date; no browser dependency.
**Verification:** `python reality_engine/cli.py fetch-headless --feeds rbi,pib` returns rows
**Dependencies:** Task 10
**Files:** `reality_engine/ingestion/headless_fetcher.py`
**Scope:** M

## Task 12: Hybrid search cutover + partitioning
**Description:** pgvector ivfflat cosine primary with `document_chunks PARTITION BY RANGE(published_date)` q1..q4, LanceDB→FTS5 fallback per `AGENTS.md:5`.
**Acceptance:** Query hits partitioned ivfflat <50ms, fallback works when embedding NULL.
**Verification:** `EXPLAIN` shows partition pruning; detach old partition without lock
**Dependencies:** Task 10
**Files:** `reality_engine/search/hybrid_search.py`
**Scope:** M

## Checkpoint: Ingestion
- [ ] Aux feeds (Vahan/MF/RBI/PIB/Budget) ingested headless; hybrid search works
- [ ] Dense substrate promotion verified (event nuance quantized, not in prose)

## Task 13: Competitive survival + never-prune structural
**Description:** `pruning_engine.py` competitive embedding survival (`explanation_weight` ↑ on survivors / ↓ on losers) + decay λ. `structural_theories.py` milestones (`profit-jump spotting`, `cheap-value traps`) carry `is_structural_milestone=1`, half-life INF, exempt from all decay.
**Acceptance:** `CALL prune_decayed_signals()` decays losers (vectors_purged>0) but retains Structural Milestone text; `explanation_weight` monotonic with explain_power.
**Verification:** `SELECT decayed_significance FROM v_ripple_decayed WHERE is_structural_milestone` non-null retained
**Dependencies:** Task 9,10
**Files:** `reality_engine/processing/pruning_engine.py`, `reality_engine/processing/structural_theories.py`
**Scope:** M

## Task 14: Distillation before deletion
**Description:** Monthly batch `[20 YouTube+4 Concalls]→LLM synthesis→UPDATE moat_evaluations/pricing_power_score→purge 24 vectors`; log `distillation_runs`. Preserves intelligence into dense substrate while reclaiming RAM.
**Acceptance:** Before purge, summary JSON stored + moat score delta applied; Structural Milestone never purged.
**Verification:** `SELECT * FROM distillation_runs ORDER BY run_date DESC LIMIT 1` correct counts
**Dependencies:** Task 13
**Files:** `reality_engine/processing/distillation_pruner.py`
**Scope:** M

## Checkpoint: Lifecycle
- [ ] Competitive pruning preserves winners; Structural Milestone survives; distillation delta applied pre-purge

## Task 15: MoE ranker + investor-majority rankings
**Description:** `ensemble_ranker.py` MoE gating with temperature + `lens_activation_log(temperature, fired_lenses)`. Persist `model_explainer_rankings(stock_id, sector_id, geo_id, regime_tag, investor_majority, lens_family, p_value, explain_power, rank)` — which model best explains which stock when, conditioned on promoter/FII/DII/retail.
**Acceptance:** `rank-models --symbol HAL --investor-majority FII` returns ranked lens families with p_value/explain_power; `lens_activation_log` shows sparse fired_lenses per temperature; per-scrip `noise_floor` learned and queryable.
**Verification:** `pytest test_quant_hardening` investor-majority ranking query; `noise-floor --symbol TITAGARH` returns value
**Dependencies:** Task 8,13
**Files:** `reality_engine/processing/ensemble_ranker.py`, `reality_engine/db/repository.py`
**Scope:** M

## Task 16: Transient event-graph + EOD corrector + orchestrator
**Description:** `event_graph.py` spawns transient graph on event (US textile tariff: parse %/effective date/exceptions/conditional US-plant, fetch remotely active dyes/yarn/cotton + machine makers, quantize 30% hit→recovery lag, 2nd-order fwd/back finds who benefits more than primary). `eod_corrector.py` continuous self-correction (EOD price+FII/DII+event batch re-ranks lenses, mutates embeddings, updates substrate). `orchestrator.py` synthesis (writer JSON/MD/HTML).
**Acceptance:** `spawn-event-graph --event US_TARIFF_TEXTILE_RELIEF --max-hops 3` returns correct 2nd-order graph; `correct-eod --universe nifty200` re-ranks + updates substrate; `run-daily-alpha --top-theses 5` exports thesis with catalyst/width/ENI/rank.
**Verification:** `pytest test_agent_and_reporting`; tariff graph case study asserts primary≠biggest beneficiary
**Dependencies:** Task 9,15
**Files:** `reality_engine/processing/event_graph.py`, `reality_engine/processing/eod_corrector.py`, `reality_engine/agent/orchestrator.py`
**Scope:** L

## Checkpoint: Complete
- [ ] Investor-majority `model_explainer_rankings` queryable per stock/sector/geo/regime
- [ ] Per-scrip noise floor learned; MoE `lens_activation_log` audit present
- [ ] Transient tariff event-graph correct (2nd-order beneficiary identified)
- [ ] EOD corrector re-ranks on EOD+FII/DII+event; SQLite fallback intact
- [ ] `test_agent_and_reporting` + `test_cli_and_dashboard` pass
