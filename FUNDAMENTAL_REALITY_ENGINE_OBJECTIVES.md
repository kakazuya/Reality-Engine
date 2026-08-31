# Fundamental Reality Engine — Core Objectives (Revised Vision 28-08-2026)

**Revised Thesis (LOCKED):** Reality Engine ingests a *lot* of data but does **NOT** store raw for a static decision tree. Raw price/volume/financials/concalls/annual reports/auxiliary (Vahan/MF/RBI/Budget/PIB/YouTube) cannot be reasoned over raw inside a limited LLM context window — a decision tree of 1000 inputs/hour is infeasible on raw text. The essence is to **analyze WHATEVER data is available to arrive at a decision EVEN WHEN information is incomplete** — that is the whole ballgame of stock prediction.

This reframes the prior PDF's narrow **Top-Down Funnel** (which was treated as THE method) into **ONE peer lens family among many**. Reasoning is **continuous and self-correcting all the time**, not a one-shot funnel. Source material: `Fundamental_Reality_Engine_Architecture.pdf` + `Quantifying Fundamental Stock Analysis Database.pdf` (Gemini 66c2f6…) + Dekosophy Adjacent Possible (619) + Investor52 Earnings/Lynch. Philosophy cornerstones below are first-class objectives, mapped to `postgres_schema.sql` + `pruning_engine.py` + `visual_evidence_artifacts`.

---

## 1. Dense Substrate vs Raw DB (Architectural Decision)

Raw storage is **insufficient** by design — the context window cannot hold finance's hell of data in raw form. We must architect a **distilled dense feature store** as the reasoning substrate, with raw kept only as audit trail / replay source.

* **Raw tier (`raw_documents`, `document_chunks`, price/volume/FII-DII feeds):** retained for provenance, re-distillation, and event replay. Never fed directly into the decision context.
* **Dense substrate (`company_distilled_parameters`, `business_model_profiles`, `macro_events`, `ripple_effects`, `model_explainer_rankings`):** compact qualitative+quantitative tensors a deep reasoning pass can actually consume. Every ingested signal is quantized into the substrate *before* it can influence a thesis.
* **Tradeoff rule:** raw ↔ dense is a deliberate compression. We lose verbatim prose to gain reasoning density. Event nuance (e.g. % reduction, effective date, exceptions, conditional vs blanket) is **quantized into the substrate**, not left in prose — see §4.
* **Schema hook:** `pruning_engine.py` governs raw→dense promotion; `distillation_runs` logs each quantization.

---

## 2. All-Peers Ensemble (FF5 is a Peer, NOT the Trunk)

The Fama-French 5-factor model is the **baseline explainer** of scrip returns, but it is **one peer among many** — every perspective competes equally for explaining power. No fixed trunk.

**Must-have peer lens families (user-mandated):**
1. **Factor/Statistical peers** — FF5 (market, SMB, HML, RMW, CMA) + any mathematical/probabilistic lens that explains even a tiny part of movement.
2. **Macro/Policy-change peer** — `regulatory_political_risks`, `macro_events`, `countries` stability. `ENI = Severity(-5→+5) × Probability(0-1)`.
3. **Business-quality / barriers / cashflow-machine peer** — `business_model_profiles` archetype + `moat_evaluations` rubric:
   ```
   Moat = 0.25*SC + 0.25*NE + 0.20*CA + 0.20*IA + 0.10*ES  (0-5)
   SC=Switching Costs, NE=Network Effects, CA=Cost Advantage, IA=Intangible/Brand/IP, ES=Efficient Scale
   Wide ≥3.5, trajectory Stable/Expanding
   ```
4. **Supply-chain / industry-linkage peer** — `ripple_effects` forward/backward transmission, `geographic_exposure` dependency criticality/severity. `PN=∏Pi`, `MN=RawN×PN×β`, `S=|MN|×20/(1+ln(1+Lag))`.
5. **Extensible peers (deferred, not dropped):** Order-flow/microstructure, behavioural sentiment — plug in as additional competing lenses later.

**Competition rule:** All peers run on every scrip; each contributes a weight to the composite explanation. The top-down funnel ordering from the old PDF is now **just one possible lens configuration**, not the sole path.

---

## 3. Continuous Self-Correction (EOD + Event-Driven)

Decisions are NOT taken when markets are closed, so we have a **window to reason heavily** on available data. Correction is **continuous**, not a nightly batch only.

* **Cadence:** Mix of (a) **EOD price movements** + **FII/DII data** + **major event** = correction signal. **NOT intraday** (99% noise unless a major player or material news — which is instead captured event-driven, see §4).
* **Per-scrip learned noise floor:** A **per-scrip adaptive noise floor** (learned by volatility/liquidity), NOT a global hard cutoff. Cutoffs exclude plain noise, but anything above a scrip's own floor is fair game for explanation.
* **Self-correcting loop:** Each EOD/event batch re-ranks peer lenses (§5), mutates embeddings (§6), and updates the dense substrate. Reasoning is never "final" — it is always revisable as new data arrives.
* **Schema hook:** `model_explainer_rankings(last_retrain, regime_tag)` + `pruning_decay_config` T½ per source type.

---

## 4. Transient Event-Graph Reasoning (Walkthrough: US Tariff Removal on Textiles)

Static DB cannot hold this reasoning — it must spawn a **transient event-graph** per material event, quantize the new reality, then reason forward/backward through the supply chain.

**Tariff example (quantized, not prose):**
1. **Parse event nuances:** % reduction, effective date, exceptions, blanket vs conditional (e.g. conditional on US plant investment). Stored as `macro_events(event_id, category=TRADE_POLICY)` + `ripple_effects` 1st-order.
2. **Fetch ALL remotely active stocks:** dyes / yarn / cotton suppliers, indirect revenue segments, machine-makers whose capex sales expand *more than* organic growth. Not just naive "buy textile" — `geographic_exposure` + `business_model_profiles` scan.
3. **Quantize new reality:** `30% revenue hit → 30% recovery`, `lag_time_months` to financials, caveats. → `ripple_effects(raw_magnitude, probability, lag_time_months)`.
4. **2nd-order forward/backward supply chain:** find who benefits **MORE than the primary** (e.g. upstream dye supplier with pricing power). Recursive CTE `postgres_schema.sql` `ripple_chain` computes `compound_probability, cumulative_magnitude, total_lag_months, significance_score` ordered `significance_score DESC`.
5. **Lifecycle:** transient graph is promoted to dense substrate (§1) then decayed per §11 once superseded/invalidated.

**Pydantic (event-graph):** `MacroEventExtraction{event_name, event_category, primary_effects:[PrimaryConsequence{target_type, target_name, transmission_channel, raw_magnitude, probability, lag_time_months, second_order_effects:[RippleConsequence{order_level≥2, downstream_ripples:[RippleConsequence]}]}]}` — emitted transactionally `repository.py` into `raw_documents→macro_events→ripple_effects`.

---

## 5. Structural Theories Never Pruned + Per-Stock/Regime Model Rankings

* **STRUCTURAL_THEORY (half-life INF, never pruned):** Auxiliary model explanations that help *permanently* — e.g. a video on spotting profit jumps early, or which cheap-on-metrics stocks to avoid. Flagged `is_structural_milestone=1`; `pruning_engine.py` retains these even when embeddings >12m. They are permanent priors, not decaying signals.
* **Model rankings are conditional, not absolute:** In one market some lenses explain more; the same lens loses p-value in another cycle. Store rankings **per stock / sector / geography / time+conditions + investor-majority type**.
* **Investor-majority conditioning:** Different majorities think differently — **promoter / FII / DII / retail**. Each applies different models, so `model_explainer_rankings` carries `investor_majority` so the same scrip shows different dominant explainers per who is driving price.
* **Schema hook:** `model_explainer_rankings(stock_id, sector_id, geo_id, regime_tag, investor_majority, lens_family, p_value, explain_power, rank)`; `pruning_decay_config.is_structural_milestone`.

---

## 6. Competitive Embedding Survival + MoE Explore/Exploit (brain/transformer sparse activation)

Embeddings will grow large — apply **brain-like competitive survival**: whatever keeps explaining movement best **wins/rises**, losers **decay**.

* **Sparse gating (MoE):** Like a transformer's sparse firing — per *ask*, only some lens pathways/parameters fire, the rest stay silent. A gating network selects active peers per scrip/regime.
* **Temperature = explore/exploit:** Each run applies small **pathway mutations** (explore) vs exploiting the current best explainer (exploit), controlled by a temperature parameter. Higher temp → test alternate decision trees/explainer paths; lower → consolidate winners.
* **Survival:** losing pathways lose weight (`explanation_weight ↓`); winning pathways `↑`. This is the embedding-space analog of neural pruning/Hebbian "cells that fire together wire together."
* **Schema hook:** `model_explainer_rankings.explanation_weight` + `lens_activation_log(temperature, fired_lenses)` for audit.

---

## 7. Multimodal Ingestion Objective

* **Sources:** Union Budget, RBI Economic Survey, MPC, YouTube analysis, earnings concall MP4, BSE announcements, Vahan/MF inflows, PIB.
* **Pipeline:** `youtube_transcriber.py` `yt-dlp → ffmpeg splitter → Whisper Large-v3 (local) + RapidOCR DirectML (AMD RX 6700 XT, no cloud)` with `timestamp_start_sec` + `pdf_ingestor.py` `PyMuPDF/Marker` layout-aware → `raw_documents(title, source_type, published_date, fiscal_period, source_url, creator_or_ministry)` → chunked `document_chunks(content, embedding VECTOR(1536) ivfflat, sector/industry_id)` for hybrid RAG. All raw is then quantized into the dense substrate (§1) before reasoning.

---

## 8. Ripple Causal DAG — Supply-Linkage Peer Lens (one of many)

* **Schema:** `macro_events(event_id, doc_id, event_name, category) → ripple_effects(ripple_id, event_id, parent_ripple_id NULL for 1st-order, order_level 1..N, target_type, target_company_id/industry_id, transmission_channel, transmission_elasticity -2→2, raw_magnitude -5→5, probability 0→1, lag_time_months)`.
* **Math:** `PN = ∏ Pi` `MN = RawN × PN × βTransmission` `S = |MN| × 20 / (1 + ln(1+Lag))`. Example steel duty: 1st +3.80 0m → 2nd -2.43 3m → 3rd -1.41 6m.
* **Recursive CTE** `postgres_schema.sql` traverses `ripple_chain` ancestor→child. This is the **supply-chain/linkage peer** (§2.4), competing equally with FF5 and others.

---

## 9. Pydantic Extraction Objective (Generalized)

```
MacroEventExtraction { event_name, event_category, primary_effects: [PrimaryConsequence{...second_order_effects:[RippleConsequence{order_level≥2, downstream_ripples:[RippleConsequence]}]}] }
AdjacentPossibleExtraction { current_node, adjacent_nodes, exploration_signal, exploitation_result, path_state:{moat_trajectory,PN,S(t)}, bayesian_update:{prior_ENI, evidence_chunk_id, posterior_ENI, confidence_delta} }
```
LLM must emit these schemas — never free-text — to populate `raw_documents→macro_events→ripple_effects` / distillation transactionally `repository.py`.

---

## 10. Gradual Migration Roadmap (Generalized)

**Phase A — Objectives freeze (done):** `AGENTS.md`, `README.md`, `postgres_schema.sql` committed.
**Phase B — Schema extension:** Run `psql -f reality_engine/db/postgres_schema.sql`; add `model_explainer_rankings`, `lens_activation_log`, `pruning_decay_config.is_structural_milestone`; backfill `business_model_profiles` Top 200.
**Phase C — Quantification backfill:** `moat_scorer.py` → `moat_evaluations` (Polyplex SC4 NE1 CA3 IA3 ES2 → 2.75 Narrow); `policy_engine.py` ENI; seed FF5 baselines + peer weights.
**Phase D — Ingestion switch:** `youtube_transcriber.py`+`pdf_ingestor.py` into `phase1_runner.py` → `raw_documents/document_chunks` → dense substrate promotion (§1).
**Phase E — Causal DAG + Event-Graph activation:** `causal_engine.py` recursive CTE; transient event-graph spawner (§4) for material news; verify `trace-causal-chain --max-hops 3`.
**Phase F — Ensemble cutover:** `composite_screener.py` refactored to **all-peers weighted ensemble** (not top-down-only); `orchestrator.py` synthesizes multi-lens thesis. Keep SQLite WAL `schema.sql` fallback until PG stable.
**Phase G — Self-correction + MoE:** EOD+event batch re-ranker (§3), temperature-gated explore/exploit (§6).

Track each phase with `python -m unittest reality_engine.tests.test_new_funnel`.

---

## 11. 4-Pillar Data Pruning & Lifecycle Framework (Generalized)

**Goal:** Prevent vector bloat, storage exhaustion, noisy RAG — math + automation. Structural milestones (§5) are exempt.

| Pillar | Mechanism | SQL Hook `postgres_schema.sql` |
|---|---|---|
| **Tiering** | Hot 12m embeddings RAM → Warm 12-36m text only → Cold >36m Parquet S3 Glacier; Video MP4 never DB | `pruning_decay_config` |
| **Exponential Decay** | `S(t)=S0·e^{-λΔt}` λ=ln2/T½: YouTube 3m λ0.231, Concall/MPC 6m λ0.115, Budget 12m λ0.058, **Structural INF** | `v_ripple_decayed` view |
| **Partitioning** | `document_chunks PARTITION BY RANGE(published_date)` quarterly ivfflat → detach old partitions | Partition DDL |
| **Procedure** | `CALL prune_decayed_signals()` cron monthly: drop embeddings >12m (retain Structural Milestone), delete ripple `prob<0.10 OR raw*prob<0.50`, archive macro >24m | `pruning_engine.py` |

Pruning rules: `PN<0.08` leaf cut, `S(t)<5.0` branch cut, status `Materialized/Superseded/Invalidated` per `processing/pruning_engine.py:30`.

---

## 12. LLM Knowledge Distillation (Before Deletion → Dense Substrate)

Monthly batch: `[20 YouTube +4 Concalls] → LLM synthesis → UPDATE business_model_profiles/moat_evaluations → purge 24 vectors` → log `distillation_runs`. Example Polyplex verbal "aerospace expansion" vs slide `Capex ₹450Cr FY29 lag 36m` → `lag_time_months=36 moat_trajectory=Stable`. Distillation is the raw→dense quantization path (§1); structural theories persist (§5).

---

## 13. Visual Alpha — Native Multimodal Vision-Language

**Why audio misses:** Slides footnotes, capex timeline bars, flowcharts, factory tours, infographics, presenter affect — `reality_engine/processing/vision_engine.py`.

| Visual Signal | Extract | Table `visual_evidence_artifacts` |
|---|---|---|
| Financial_Table_Slide | OCR fine-print, order backlog | `extracted_visual_data JSONB` |
| Value_Chain_Diagram | Supplier integration → moat mechanics | `moat_implication` |
| Factory_Floor_Tour | Machine density, inventory → operating leverage | `frame_snapshot_url` S3 |

Pipeline: `MP4 → ffmpeg scene-change → RapidOCR DirectML (RX 6700 XT) + OpenCV + Whisper → VisualArtifact` Pydantic `VideoIntelligenceExtraction{spoken_policy_signals[], visual_artifacts[]}` → `visual_evidence_artifacts(...)` `reality_engine/agent/schemas.py:344` + `postgres_schema.sql` — fully local. Concrete: Aerospace slide ₹450Cr vs ₹1,200Cr FY29 delay flagged `lag_time_months 36` via vision → DAG corrected.

Track via `python -m unittest reality_engine/tests/test_pruning_vision` + monthly `CALL prune_decayed_signals()`.

---

## 14. Philosophical Cornerstones — Adjacent Possible (Transcript 4 Levels)

Transcript `raw_documents: doc_id DEKO-619` → Pydantic `VideoIntelligenceExtraction`.

* **Level 1 — Adjacent Possible + Graph:** `ripple_effects.parent_ripple_id ≈ adjacent nodes`; top-down funnel is just *one* graph traversal among many. `causal_engine.py` recursive CTE prunes `PN<0.08` unreachable paths.
* **Level 2 — Serendipity + Exploration:** `inbox_runner.py`+`telegram_client.py` serendipitous filings (Polyplex PPT missed by category query). Exploration cron `run-inbox --explore` → exploit when `moat_updates>0.2`. Maps to §6 temperature explore.
* **Level 3 — Path Dependence + DP:** `moat_trajectory` memoized state; `distillation_runs` DP table increments, not from zero; `MN=RawN×PN×β` stateful product.
* **Level 4 — Bayesian Updating + VoI:** `ENI=Severity×Probability` prior×likelihood → posterior; `significance_rank=|MN|×20/(1+ln(1+Lag))` discounts lag. Value-of-information cron: small `screen --top 5` before big bet.

Dashboards surface `adjacent nodes count`, `exploration vs exploitation ratio`, `path dependence lag`, `evidence delta`.

---

## 15. Earnings Growth Equation — 5 Ways (Investor52 `oEUg7NwABnM`)

`Revenue = Price × Units Sold` → `Earnings = Revenue - Costs`. **5 ways (all map to `financial_metrics`+`moat_evaluations`, competing as quality/peer lenses):**
1. **Reduce Costs → Margins** `gross/operating/net_margin_peer_percentile` → `moat_evaluations.cost_advantage`.
2. **Increase Price (Pricing Power)** `pricing_power_score` + tariff ENI tailwind.
3. **Sell More Units** `industries.secular_growth_score≥4` + capacity utilization `Factory_Floor_Tour`.
4. **Acquire/Roll-up** Tollbooth/Platform synergy vs `debt_to_ebitda` gate.
5. **New Markets/Products** `geographic_exposure revenue_share_pct` + Investor_Presentation tables.
Every `quarterly_financials` recomputes `ΔEarnings = f(ΔPrice,ΔUnits,ΔCosts)`; `moat_scorer.py` tags structural vs cyclical.

---

## 16. Lynch 6 Stock Types — Archetype & Lifecycle Filter (Investor52 `-XF-gs_SXnA`)

6 shapes = revenue/earnings trajectories: **Stalwart** (steady 10-19%), **Fast Grower** (>20%), **Slow Grower** (<10%), **Cyclical** (wave, ~25% S&P), **Turnaround** (drop→recover), **Asset Play** (hidden value). Map to `lifecycle_stage`+`archetype`+`moat_evaluations`; `composite_screener.py` tags `stock_type` via 10y `yoy_revenue_growth_pct` + peer percentile. These are **lens features feeding the ensemble**, not a standalone funnel.

---

## 17. Visual Evidence Learnings — Images Parsed (Local GPU OCR 2026-08-24)

Pipeline `vision_engine.py:39` RapidOCR DirectML `RX 6700 XT`: `hi_oEUg7NwABnM.mp4` 77.3MiB + `hi_-XF-gs_SXnA.mp4` 64.7MiB → `ffmpeg fps=1/5` 24 frames each → RapidOCR 0.9s/frame → **100 `visual_evidence_artifacts`** `Financial_Table_Slide 66/100` conf 0.87-0.92. Learnings: equation slide `Revenue=Price×Units-Costs` (5 arrows), 5-Ways header, margin tables vs competitor, HelloStocks.ai +141.9% beating market, Lynch 29% header, wave/drop/recovered shapes OCR'd as `wave pattern`. All rows retain `extracted_visual_data JSONB` + `visual_description` + `moat_implication` + `frame_snapshot_url`. Local DirectML, not Gemini.

---

**Summary of what changed & why:**
1. **Header/thesis rewritten** — raw DB insufficient due to context window; dense substrate + incomplete-info decisioning is the core goal.
2. **Old §1 Top-Down Funnel demoted** to one peer lens family inside new **§2 All-Peers Ensemble** (FF5 is a baseline peer, not the trunk); macro/policy, quality/moat, supply-linkage are must-have peers; microstructure/behavioural deferred but extensible.
3. **NEW §1 Dense Substrate vs Raw DB** — explains architectural why-raw-fails and raw↔dense tradeoff.
4. **NEW §3 Continuous Self-Correction** — EOD price+FII/DII+event batch, per-scrip learned noise floor (not global cutoff), no intraday.
5. **NEW §4 Transient Event-Graph Reasoning** — tariff walkthrough quantized, forward/backward 2nd-order supply chain, transient graph lifecycle.
6. **NEW §5 Structural Theories Never Pruned + Per-Stock/Regime Rankings** — `is_structural_milestone=1`, INF half-life, investor-majority (promoter/FII/DII/retail) conditioning.
7. **NEW §6 Competitive Embedding Survival + MoE Explore/Exploit** — sparse gating, temperature, pathway mutation, survival weighting.
8. **Migration roadmap (§10) generalized** to ensemble + self-correction + MoE phases; **pruning (§11)** exempts structural milestones; **Adjacent Possible (§14)** reframed as one graph traversal among many, Level 2 ↔ §6 temperature; **Earnings/Lynch (§15-16)** now feed ensemble lenses, not a sole funnel.
9. **Preserved verbatim:** Moat formula, ENI, PN/MN/S math, decay λ table, visual pipeline, all schema hooks (`postgres_schema.sql`, `pruning_engine.py`, `visual_evidence_artifacts`, `repository.py`). No PII/keys fabricated.
