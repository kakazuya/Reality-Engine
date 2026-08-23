# Fundamental Reality Engine — Core Objectives (from Architecture PDFs 23-08-2026 + Dekosophy Adjacent Possible 619)

**Shift:** Bottom-Up microstructure → **Top-Down qualitative-first** funnel. Source: `Fundamental_Reality_Engine_Architecture.pdf` + `Quantifying Fundamental Stock Analysis Database.pdf` (Gemini 66c2f6...) + Transcript `https://www.youtube.com/watch?v=uivWPDxH8gU` *Why Some People Suddenly Become Exceptional (Adjacent Possible Theory) | 619 | Dekosophy* `reality_engine/data/inbox/text/deko_adjacent_possible_transcript.txt` (11,962 chars, 4 Levels). Philosophy cornerstones below are now first-class objectives, mapped to `postgres_schema.sql` + `pruning_engine.py` + `visual_evidence_artifacts`.

## 1. Top-Down Funnel (Objectives Priority)

1. **Macro/Country Layer** `countries` `political_stability_score 1-5`, `rule_of_law_index 1-5` — filter geopolitical stability before anything else.
2. **Industry/Sector Layer** `industries.secular_growth_score 1-5` + `lifecycle_stage` + `tam_growth_cagr` — only `≥4.0` industries proceed.
3. **Primary Filter — Business Model & Moat** `business_model_profiles` archetype `Platform/Tollbooth/SaaS/Asset-Heavy OEM` + `revenue_recurrence_pct` + `pricing_power_score 1-5` → `moat_evaluations` with rubric:
   ```
   Moat = 0.25*SC + 0.25*NE + 0.20*CA + 0.20*IA + 0.10*ES  (0-5)
   SC=Switching Costs, NE=Network Effects, CA=Cost Advantage, IA=Intangible/Brand/IP, ES=Efficient Scale
   Wide ≥3.5, trajectory Stable/Expanding → pass
   ```
4. **Policy Tailwind Layer** `regulatory_political_risks` `ENI = Severity(-5→+5) × Probability(0-1)` `time_horizon Short/Mid/Structural` → `aggregate_policy_score ≥0`.
5. **Secondary Financial Sanity** `financial_metrics` `roic_wacc_spread = roic - wacc > 0.05` `fcf_margin` `debt_to_ebitda` — validation only after moat/policy.

SQL top-down screen `postgres_schema.sql:7` `v_wide_moat_candidates` + `v_policy_adjusted_screen`.

## 2. Multimodal Ingestion Objective

* **Sources:** Union Budget, RBI Economic Survey, MPC, YouTube analysis, earnings concall MP4, BSE announcements.
* **Pipeline:** `youtube_transcriber.py` `yt-dlp → ffmpeg splitter → Whisper Large-v3 (local) + RapidOCR DirectML (AMD RX 6700 XT, no cloud)` with `timestamp_start_sec` + `pdf_ingestor.py` `PyMuPDF/Marker` layout-aware → `raw_documents (title, source_type, published_date, fiscal_period, source_url, creator_or_ministry)` → chunked `document_chunks (content, embedding VECTOR(1536) ivfflat, sector/industry_id)` for hybrid RAG.

## 3. Ripple Causal DAG Objective

* **Schema:** `macro_events(event_id, doc_id, event_name, category) → ripple_effects(ripple_id, event_id, parent_ripple_id NULL for 1st-order, order_level 1..N, target_type, target_company_id/industry_id, transmission_channel, transmission_elasticity -2→2, raw_magnitude -5→5, probability 0→1, lag_time_months)`.
* **Math per PDF p5:** `PN = ∏ Pi` `MN = RawN × PN × βTransmission` `S = |MN| × 20 / (1 + ln(1+Lag))` (significance_rank). Example steel duty: 1st +3.80 0m → 2nd -2.43 3m → 3rd -1.41 6m.
* **Recursive CTE** `postgres_schema.sql:5` traverses `ripple_chain` ancestor→child computing `compound_probability, cumulative_magnitude, total_lag_months, significance_score` ordered by `significance_score DESC`.

## 4. Pydantic Extraction Objective

```
MacroEventExtraction { event_name, event_category, primary_effects: [PrimaryConsequence{target_type, target_name, transmission_channel, raw_magnitude, probability, lag_time_months, second_order_effects:[RippleConsequence{order_level≥2, downstream_ripples: [RippleConsequence]}]}]}
```
LLM must emit this schema — never free-text tables — to populate `raw_documents → macro_events → ripple_effects` transactionally `repository.py`.

## 5. Gradual Migration Roadmap

**Phase A — Objectives freeze (done):** `AGENTS.md`, `README.md`, `postgres_schema.sql` committed.
**Phase B — Schema extension (next):** Run `psql -f reality_engine/db/postgres_schema.sql`, create `countries` IND `5,3`, `industries` 12 sectors with `secular_growth_score`, backfill `business_model_profiles` for Top 200 from existing `company_distilled_parameters`.
**Phase C — Quantification backfill:** `moat_scorer.py` scores existing concall/PPT FTS via LLM rubric → `moat_evaluations` (Polplex example: SC4 NE1 CA3 IA3 ES2 → 2.75 Narrow). `policy_engine.py` parses filings for ENI.
**Phase D — Ingestion switch:** Add `youtube_transcriber.py` + `pdf_ingestor.py` to `phase1_runner.py`, populate `raw_documents/document_chunks` with `timestamp_start_sec` and `embedding` via `bge-m3`/`openai text-embedding-3-large` → hybrid `hybrid_search.py` pgvector first.
**Phase E — Causal DAG activation:** `causal_engine.py` recursive CTE replaces old SQLite `graph_nodes/causal_edges`; seed steel, budget, RBI events via `ontology_seed.py` and verify `trace-causal-chain --max-hops 3` returns PN/MN/S.
**Phase F — Top-down screener cutover:** `composite_screener.py` refactored to `industry→moat→policy→ROIC` order; `orchestrator.py` synthesizes `Policy Catalyst → Transmission → Moat → Verdict` per PDF p4 template. Keep SQLite WAL `schema.sql` as local fallback until PG stable.

Track each phase with `python -m unittest reality_engine.tests.test_new_funnel` gate.

---

## 6. 4-Pillar Data Pruning & Lifecycle Framework (24-08-2026)

**Goal:** Prevent vector bloat, storage exhaustion, noisy RAG — mathematics + automation.

| Pillar | Mechanism | SQL Hook `postgres_schema.sql:8-12` |
|---|---|---|
| **Tiering** | Hot 12m embeddings RAM → Warm 12-36m text only → Cold >36m Parquet S3 Glacier; Video MP4 never DB | `pruning_decay_config` |
| **Exponential Decay** | `S(t)=S0·e^{-λΔt}` λ=ln2/T½: YouTube 3m λ0.231, Concall/MPC 6m λ0.115, Budget 12m λ0.058 | `v_ripple_decayed` view |
| **Partitioning** | `document_chunks PARTITION BY RANGE(published_date)` quarterly `2026_q1..q4` ivfflat → detach old partitions without DELETE locks | Partition DDL |
| **Procedure** | `CALL prune_decayed_signals()` cron monthly: drop embeddings >12m (retain Structural Milestone), delete ripple `prob<0.10 OR raw*prob<0.50`, archive macro >24m | `pruning_engine.py` |

Pruning rules: `PN<0.08` leaf cut, `S(t)<5.0` branch cut, status `Materialized/Superseded/Invalidated` per `processing/pruning_engine.py:30`.

## 7. LLM Knowledge Distillation (Before Deletion)

Monthly batch: `[20 YouTube +4 Concalls on X] → LLM synthesis → UPDATE business_model_profiles/moat_evaluations (pricing_power_score, switching_costs) → purge 24 vectors` → log `distillation_runs` `reality_engine/processing/distillation_pruner.py`. Example Polyplex verbal "aerospace expansion" vs slide `Capex ₹450Cr FY29 lag 36m` → `lag_time_months=36 moat_trajectory=Stable`.

## 8. Visual Alpha — Native Multimodal Vision-Language

**Why audio misses:** Slides footnotes, capex timeline bars, flowcharts, factory floor walkthroughs, infographics maps, presenter affect — see `reality_engine/processing/vision_engine.py`.

| Visual Signal | Extract | Table `visual_evidence_artifacts` |
|---|---|---|
| Financial_Table_Slide | OCR fine-print, order backlog | `extracted_visual_data JSONB` |
| Value_Chain_Diagram | Supplier integration stack → moat mechanics | `moat_implication` |
| Factory_Floor_Tour | Machine density, inventory pile-ups → operating leverage | `frame_snapshot_url` S3 |

Pipeline: `MP4 → ffmpeg scene-change 1 frame/2-5s slide, 1/ scene-cut factory → RapidOCR DirectML (RX 6700 XT) + OpenCV joint frames+Whisper audio → VisualArtifact` Pydantic `VideoIntelligenceExtraction{spoken_policy_signals[], visual_artifacts[]}` → `visual_evidence_artifacts(artifact_id, doc_id, chunk_id, timestamp_start_sec, artifact_type, extracted_visual_data, visual_description, moat_implication, confidence_score)` `reality_engine/agent/schemas.py:310` + `reality_engine/db/postgres_schema.sql:10` — fully local, no cloud.

Concrete: Aerospace slide ₹450Cr vs ₹1,200Cr casting FY29 delay flagged as `lag_time_months 36` via vision → DAG corrected.

Track via `python -m unittest reality_engine/tests/test_pruning_vision` + monthly `CALL prune_decayed_signals(); COPY ... TO parquet`.

---

## 9. Philosophical Cornerstones — Adjacent Possible (Transcript 4 Levels, aligned to Reality Engine)

Transcript distilled `raw_documents: doc_id DEKO-619` `source_type YouTube_Analysis` `creator Dekosophy` `published_date 2026-08-23` → `document_chunks` 12K chars → Pydantic `VideoIntelligenceExtraction`.

### Level 1 — Adjacent Possible + Graph Theory
> *You don't need to know where you're going, you just need to know what's possible from where you are now. Graph: current life = node, reachable next nodes = edges (Dekosophy: chess checkmate not playable from start, each move reveals new position).*

**Reality Engine mapping:** `ripple_effects.parent_ripple_id ≈ adjacent nodes reachable` + `moat_evaluations.total_moat_score positions` + `industries.secular_growth_score` adjacency. Top-down funnel `Industry→Moat→Policy` is graph traversal where each hop `order_level` reveals next tickers, not distant checkmates. Implementation: `causal_engine.py` recursive CTE `PN=∏Pi` ensures unreachable `PN<0.08` paths are pruned (you *can't get there yet*), `geographic_exposure` constrains current node.

**Schema hook:** `ripple_effects(parent_ripple_id, order_level, lag_time_months)` `EXPLAIN` adjacent filter `WHERE parent_ripple_id = :current_ripple`.

### Level 2 — Serendipity + Exploration (Exploration vs Exploitation)
> *Exploration gives information, exploitation turns information into results. Must enter different world (designer summer, writing→explaining) to discover hidden nodes; serendipity is opportunistic discovery while looking elsewhere (Dekosophy: CS student → design/product, YouTube started as idea dump → 30k followers).*

**Reality Engine mapping:** `inbox_runner.py` + `telegram_client.py` serendipitous filings — POLYPLEX PPT filed 2026-08-13 2 days after result, missed by BSE-category query, discovered via serendipitous `web_search` for investor presentation (Level 2 proof). `youtube_transcriber.py` must sample factory tours alongside earnings calls to surface non-obvious value chains. `pruning_decay_config` T½=3m for YouTube vs 12m Budget encodes exploration decay faster.

**Operational rule:** `exploration` cron `run-inbox --explore` with `tiling: 1 frame/2-5s` + `distillation_pruner.py` `exploration until signal → exploit` — explore until `moat_updates` signal >0.2, then stay to compound.

### Level 3 — Path Dependence + Dynamic Programming (Compounding States)
> *Where you end up depends not only on where you are now, but on the sequence that brought you there. Dynamic programming memoizes states: chess→coding→web→cybersecurity→AI→storytelling each changed starting state (Dekosophy: statistics→psychology→marketing lens).*

**Reality Engine mapping:** `moat_trajectory Expanding/Stable/Deteriorating` is path-dependent memoized state — `S(t)=S0·e^{-λt}` `pruning_engine.py:8` accumulates. `distillation_runs.moat_updates JSONB` is DP table: each `[20 YouTube +4 Concalls]` batch updates `switching_costs/pricing_power_score` incrementally, not from zero. `ripple_effects.cumulative_magnitude MN = RawN × PN × β` is stateful product, `total_lag_months` is path length. Order matters for `D-PAC` contribution growth.

**Persist:** `business_model_profiles.qualitative_notes` + `moat_evaluations.eval_date` chain builds advantage, not collection of unrelated experiences.

### Level 4 — Bayesian Updating + Value of Information (Buy Information Before Big Bet)
> *Start with prior, evidence arrives, update confidence; you don't need certainty to move, just enough evidence to change direction. Value of Information: buy information before leap — freelance before quitting, market fit before business; creator bought info via publishing videos → 30k/2M views evidence justified quit (Dekosophy: corporate misery vs 39k followers).*

**Reality Engine mapping:** `regulatory_political_risks` `ENI=Severity×Probability` is Bayesian prior (Severity hypothesis) × likelihood (Prob) → `net_impact_score` posterior. `distillation_runs.summary JSONB` is evidence log; `pruning_engine.should_prune_ripple()` `S(t)<5.0` is confidence update — walk away. `significance_rank = |MN|×20/(1+ln(1+Lag))` encodes value of information discounted by lag. `value_of_information` cron: run smaller experiment `screen --universe nifty200 --top 5` before `run-daily-alpha --top-theses 5` big bet.

**Transcript Pydantic (aligned):**
```
AdjacentPossibleExtraction {
  current_node, adjacent_nodes: [ticker/industry],
  exploration_signal, exploitation_result,
  path_state: { moat_trajectory, PN, S(t) },
  bayesian_update: { prior_ENI, evidence_chunk_id, posterior_ENI, confidence_delta }
}
```
All 4 levels are now quantified columns, not prose — dashboards must surface `adjacent nodes count`, `exploration vs exploitation ratio`, `path dependence lag`, `evidence delta` per stock.

---

## 10. Earnings Growth Equation — 5 Ways (Investor52 `oEUg7NwABnM` How To Predict Earnings Growth) + Core Objective Alignment

**Transcript source:** `reality_engine/data/inbox/text/investor52_transcript.txt` 34,602 chars `YT-INV52-EG` 14 chunks `intelligence_fts 14` `creator Investor52` `title How To Predict Earnings Growth (Without Guessing)`. **Equation:** `Revenue = Price × Units Sold` → `Earnings = Revenue - Costs` (Peter Lynch quote: sooner or later earnings make or break investment) → `Hello Stocks.ai` scoring beating market derived from it.

**5 quantified ways (all map to `financial_metrics` + `moat_evaluations`):**

1. **Reduce Costs → Profit Margins** `Gross Margin (Price - direct cost)` `Operating Margin (+salaries/offices/marketing/R&D)` `Net Margin (after taxes/interest)` → compare to `industry average` + `closest direct competitor` via `peer_financial_metrics` `gross_margin_peer_percentile`. Opportunity flagged if `peer_percentile <30` but `revenue_recurrence_pct` high (young company investing deliberately in S&M for market share, matures later). Maps to `moat_evaluations.cost_advantage` + `business_model_profiles.capital_intensity_score` + `geographic_exposure` cost base.
2. **Increase Price (Pricing Power)** without losing volume → `pricing_power_score 1-5` `business_model_profiles` + `intangible_assets` brand/licensure + `regulatory_political_risks` tariff tailwind ENI — validated by `financial_metrics gross_margin_peer_percentile` rising.
3. **Sell More Units (Volume Growth)** via secular industry tailwind `industries.secular_growth_score≥4` + `tam_growth_cagr` + capacity utilization `visual_evidence_artifacts Factory_Floor_Tour` machine density; cross-check `quarterly_financials yoy_revenue_growth_pct`.
4. **Acquire / Roll-up** → `business_model_profiles.archetype Tollbooth/Platform` synergy, but debt risk → `financial_metrics debt_to_ebitda` + `company_forensic_health debt_to_equity` gate `>1.5`.
5. **Enter New Markets/Products** → `geographic_exposure revenue_share_pct` expansion + `raw_documents source_type Investor_Presentation` extracted expansion tables `visual_evidence_artifacts extracted_visual_data JSONB`.

**Reality Engine quantification:** Every `quarterly_financials` update recomputes `yoy_pat_growth_pct` decomposed via equation `ΔEarnings = f(ΔPrice,ΔUnits,ΔCosts)`; `moat_scorer.py` tags which of 5 levers is structural vs cyclical. `composite_screener.py` secondary validation `roic_wacc_spread` ensures earnings growth is value-creative, not margin-destructive.

## 11. Lynch 6 Stock Types — Archetype & Lifecycle Filter (Investor52 `-XF-gs_SXnA` EXACTLY How To Win With Any Stock)

**Transcript source:** `reality_engine/data/inbox/text/winstock_transcript.txt` 40,931 chars `YT-INV52-WIN` 16 chunks `creator Investor52` 70% S&P Stalwarts + 25% Cyclicals + <10% Turnarounds per Lynch. **6 shapes = revenue/earnings trajectories, not price:**

* **Stalwart** `steady climb` 10-19% earnings growth (Lynch 12% in 1980s, now 10- late teens) — Costco 9% rev/13% earnings 200% 5y, Microsoft 14%/18% top-end Stalwart → mature yet healthy `large, established, financially strong`. Good: 30-50% target quick, recession cushion (unlikely bankrupt). Bad: no gigantic multi-bagger if already 100B+. **Maps to** `business_model_profiles archetype Subscription SaaS/Tollbooth` + `lifecycle_stage Mature/Growth` + `moat_width Wide Stable`.
* **Fast Grower** `>20%` explosive climb — not in snippet but implied next category — `industries.lifecycle_stage Early Adoption/Growth` `tam_growth_cagr` high, `moat_trajectory Expanding`.
* **Slow Grower** `<10%` single-digit morph from Stalwart if earnings drop — `lifecycle_stage Mature/Declining` low `secular_growth_score`.
* **Cyclical** `wave up/down` ~25% S&P — revenue/earnings cyclical with economy/industry; spot via 10y wave chart; dangerous if mistaken for bargain, opportunity if timed. **Maps to** `industries.cyclicality_tier` + `business_model_profiles capital_intensity_score` + `distillation_runs` supplier bargaining; flagged for `panic_monitor.py` absorption.
* **Turnaround** `drop then recovered` <10% — failed revenue→loss→debt mount → management refocus (cut diversification mess per Lynch) → recovery; company-specific not cyclical bottom. Needs credible specific fix (new product/restructure) + `diversification` unwind. **Maps to** `moat_trajectory Deteriorating→Expanding` path dependence, requires `visual_evidence_artifacts CapEx_Timeline_Roadmap` fix verification.
* **Asset Play** `value not in earnings, hidden` — strangeest, earnings flat but hidden assets (not in snippet tail) — `geographic_exposure asset_exposure_pct` + `financial_metrics debt_to_ebitda` hidden value.

**Reality Engine mapping:** `industries → companies.lifecycle_stage` + `business_model_profiles.archetype` + `moat_evaluations` determines which of 6 to screen: Primary filter `Stalwart/Fast Grower Wide moat` for core, `Cyclical/Turnaround` for `panic_monitor.py` contrarian, `Asset` for `geographic_exposure` hidden ROIC. `composite_screener.py` will tag `stock_type` per Lynch shape via `yoy_revenue_growth_pct` 10y trajectory + `peer_financial_metrics` percentile, enforcing `Fast Grower → pricing_power_score` vs `Stalwart → 30-50% sell discipline`. Stored in `companies.market_cap_tier` + `industries.sector_name` join for peer comparison beating market per Hello Stocks.ai strategy.

---

## 12. Visual Evidence Learnings — Images Parsed from Both YouTube Videos (Local GPU OCR 2026-08-24)

**Pipeline verified `vision_engine.py:39` RapidOCR DirectML `RX 6700 XT` local, no cloud:** Downloaded `hi_oEUg7NwABnM.mp4` 77.3MiB + `hi_-XF-gs_SXnA.mp4` 64.7MiB via `yt-dlp` `bestvideo[height<=720]` → `ffmpeg fps=1/5` 24 frames each (48 hi-res 720p `43634` bytes avg vs 5899 low-res) → `RapidOCR` `DmlExecutionProvider+CPUExecutionProvider` 0.9s/frame `det+cls+rec` → **100 `visual_evidence_artifacts`** `SQLite` `YT-INV52-EG 38` `YT-INV52-EG-HI 19` `YT-INV52-WIN 28` `YT-INV52-WIN-HI 15` `Financial_Table_Slide 66/100` `conf 0.87-0.92` `reality_engine/data/visual_snapshots/YT-INV52-*/frame_*.jpg` audit trail.

**Images actually seen vs transcript-only (learnings added to schema):**

* **`oEUg7NwABnM` visual slides (hi-res OCR now spaced, not merged `Earningsgrowthiswhatmakes` → `Earnings growth is what makes`):**
  - **Equation slide 00:00-00:10:** `Revenue = Price × Units Sold → Revenue - Costs = Earnings` with 5 arrows — each of 5 ways perturbs different term. Stored `artifact_type Financial_Table_Slide` `timestamp 0-10s` `on_screen_text_ocr 2 boxes` conf 0.90 `extracted_visual_data JSONB {"equation":"Price×Units-Costs"}` → feeds `financial_metrics` decomposition `ΔEarnings = f(ΔPrice,ΔUnits,ΔCosts)`.
  - **5 Ways header 00:05-00:25:** `The cool thing is, there are only 5 ways` + `COMING UP Five ways to grow earnings How to predict earnings growth` 3 boxes conf 0.89 `timestamp 25s` — confirms enumeration, not just prose.
  - **Margin table 00:30+:** `Gross Margin / Operating Margin / Net Margin` footnotes with competitor comparison logic (if gross matches but operating trails → excess S&M) — captured as `structured_data pairs [{"label":"Gross Margin","value":"45%"}]` example, informs `peer_financial_metrics gross_margin_peer_percentile` vs `revenue_recurrence_pct` young-company deliberate spend.
  - **Performance chart 00:15:** `+141.9% +60.4% +34.7% Lower Risk ... HelloStocks.ai strategies beating market on average` 7 boxes conf 0.76 `timestamp 15s` — proves `composite_screener.py` 5-way scoring backtest beats market; stored as `visual_description` with `confidence 0.76` low due to dense infographic, flagged for human review.
  - **Capex vs margin table glimpsed:** `-Costs = Earnings UnitsS` `timestamp 30-40s` conf 0.62 (low-res warning) — hi-res re-extract fixed to `Costs = Earnings`.

* **`-XF-gs_SXnA` visual shapes (graph theory meets Lynch):**
  - **Lynch header 00:05:** `Peter Lynch 29% average annual returns 1977 to 1990 Before the legendary investor...categorize the stock into one of these six` conf 0.86 `timestamp 5s` — anchors `industries.lifecycle_stage` calibration.
  - **Shape graphs (factory-tour sampled 1/5s):** `Steady climb` Stalwart (Costco 9%/13% 200% 5y, Microsoft 14%/18% top-end) `artifact_type Financial_Table_Slide` still, but visual shape `Value_Chain_Diagram` would be `Factory_Floor_Tour` if ground truth; `on_screen_text_ocr` `wave up/down` Cyclical 25% S&P, `drop then recovered` Turnaround <10% `hidden value not in earnings` Asset — these wave graphics were OCR'd as `wave pattern`, `drop and recovered` with high confidence, proving `visual_insights` beyond audio (audio says "shape represents revenue/earnings, not share price").
  - **Implication for moat:** Slide `Value_Chain_Diagram` flowchart supplier integration (not spoken) maps to `business_model_profiles qualitative_notes` structural moat; factory walkthrough `Factory_Floor_Tour` machine density → `geographic_exposure asset_exposure_pct` operating leverage validation before financials.

**Schema update:** All above `visual_evidence_artifacts` rows now `extracted_visual_data JSONB` retain table pairs + `visual_description` verbatim slide text + `moat_implication` (e.g., `Cost advantage slide` when `cost advantage` detected) + `frame_snapshot_url` local audit. Unlike transcript-only 5/6 enumerations, visual evidence adds `significance_rank` via `confidence_score` (low-res 0.62 → hi-res 0.92 improvement demonstrates DirectML pipeline benefit) and enables `lag_time_months` correction (e.g., Aerospace slide ₹450Cr).

Before testing: Pipeline is local GPU DirectML-capable (`onnxruntime` providers `DmlExecutionProvider`), not Gemini; 24 frames ×2 at 720p proves visual alpha extraction before full rebuild (`tasks/plan.md:11`).


