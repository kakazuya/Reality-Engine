# Next Wave Execution Plan — Fresh Session | 2026-08-29 11:33 UTC

> **Handoff for fresh session:** Core + second-tier macro data is LOADED. Reasoning/d Dense substrate promotion + All-Peers Ensemble + MoE + Transient Graph + EOD Corrector is NEXT. This file is the sole source for the next session — do not re-read prior handoffs, just execute wave by wave.

## 0. Session Entry Snapshot (what is ready)

**Core (tier-1):**
- DB `equity_intelligence.db` ~1GB, 94k corporate_documents deduped, 3,472 masters (ISIN anchor), 2.7M daily_price_delivery, financials, PIT, Bulk/Block, forensic gates
- Tests: 103 OK (`Ran 103 tests ... OK`)

**Second-tier macro (last 2 FYs, freshly loaded):**
- Centre: Union Budget 2024-25 (I+Full) + 2025-26 + Economic Survey 2024-25/2025-26 — 6 docs
- States: UP 2, TN 2, MH 2, TG 2, HR 3, AP 4, KA 1 = 14 `State_Budget_*` docs (GJ 0 graceful skip — WebForms JS wall, documented)
- RBI: Annual 2024-25 + FSR 2025-26 (via listing discovery, 8MB) — 2 docs
- PIB: 1 doc
- Total: 27 PDFs `reality_engine/data/macro_pdfs`, 72 `raw_documents`, 2067 `document_chunks` (state 378, rbi 299), FTS 2714, `pruning_decay_config` seeded (Union 12m, State 12m, Survey 12m, RBI 6m, PIB 3m)
- CLI: `fetch-macro`/`fetch-headless`/`process-macro` with `--ingest` and `--dry-run`, listing discovery + sanitize, browser fallback fixed (`headless_fetcher` now navigates target)

**Already wired:** `config.py` endpoints, `macro_pdf_fetcher.py`, `pdf_ingestor.ingest_macro_*`, `pruning_engine` half-lives + `macro_source_type_to_category`, `macro_runner.py`, tests `test_macro_pdf_fetcher` (13) + `test_macro_ingest` (4)

## 1. Next Wave Goal

Quantize every `raw_documents→document_chunks` into the **dense substrate** (`company_distilled_parameters`, `business_model_profiles`/`moat_evaluations`, `macro_events`/`ripple_effects`, `model_explainer_rankings`) then compete them via **all-peers weighted ensemble** with **per-scrip learned noise floor** + **MoE temperature** + **continuous self-correction** (EOD price+FII/DII+event). Raw never enters decision context.

## 2. Wave Structure (execute sequentially, parallelize only where noted)

### Wave A — Dense Distillation (Foundation for all peers)
**Goal:** Every macro PDF chunk → Pydantic lens → substrate rows before any thesis.

- **Task A1 — Distill macro chunks → `macro_events` + `ripple_effects`**
  - File: `reality_engine/processing/distillation_engine.py` + new `distill_macro_document(doc_id)` 
  - Logic: `DocumentParser` → `MaxMacroEventExtraction` / `AdjacentPossibleExtraction` (schemas.py) → `repository.upsert_macro_event` + `ripple_effects(parent_ripple_id, order_level, raw_magnitude, probability, lag_time_months, transmission_elasticity, significance_rank)`
  - Parse nuance: `% reduction, effective date, exceptions, conditional vs blanket (e.g. conditional US plant)` — quantized, not prose.
  - Acceptance: For each Union/State budget doc, `SELECT count(*) FROM macro_events WHERE doc_id=?` ≥1; `ripple_effects` has 1st-order rows with `probability>0` and `lag_time_months` not null.
  - Verification: `python -m unittest reality_engine.tests.test_distillation_macro -v` (new) — mock LLM via deterministic fixture.

- **Task A2 — Business-quality peer backfill (Moat) from filings + macro hints**
  - File: `reality_engine/processing/moat_scorer.py`, `business_profiler.py`
  - Logic: `Moat=0.25*SC+0.25*NE+0.20*CA+0.20*IA+0.10*ES`, `width Wide≥3.5`, `trajectory Stable/Expanding` → `moat_evaluations` + `business_model_profiles(archetype,pricing_power)`
  - Acceptance: POLYPLEX 4/1/3/3/2→2.75 Narrow stored via `moat_scorer.score_from_text`; Top 20 seeded.
  - Parallel with A1? **Yes** — touches different tables.

**Checkpoint A:** `SELECT source_type, count(*) FROM raw_documents GROUP BY source_type` matches distilled counts; no raw prose leaks to substrate.

### Wave B — Peers as Competing Ensemble + FF5
**Goal:** Quality / Policy / Supply peers are queryable and weighted with FF5 factor peer.

- **Task B1 — Policy ENI peer**
  - File: `policy_engine.py`
  - Formula `ENI=Severity(-5→+5)*Prob(0-1)`, `AggENI=ΣENI` → `regulatory_political_risks(net_impact_score GENERATED)`; pass `AggENI≥0`.
  - Acceptance: steel duty case stored; `v_policy_adjusted_screen` queryable.

- **Task B2 — Supply-chain peer**
  - File: `causal_engine.py`, `geographic_exposure`
  - Math `PN=∏Pi`, `MN=RawN*PN*β`, `S=|MN|*20/(1+ln(1+Lag))`, recursive CTE `ripple_chain`, prune `PN<0.08`/`S(t)<5.0`.
  - Acceptance: steel duty 3-level chain verified (`1st +3.80 0m → 2nd -2.43 3m → 3rd -1.41 6m` ordered `S DESC`).

- **Task B3 — FF5 factor peer + `composite_screener` refactor to weighted ensemble**
  - Files: `technical_engine.py` (S_TechFlow), `fundamental_engine.py` (S_Funda), `composite_screener.py`
  - Remove top-down funnel trunk; implement `composite = Σ w_lens*norm(lens_score)` where `w_lens = explain_power / Σexplain_power` per `(stock/sector/geo/regime/investor_majority)`.
  - Per-scrip learned noise floor (vol/liquidity adaptive) replaces global hard cutoff; `eod_corrector` will learn it (B3 wires stub, B5 learns).
  - Acceptance: `screen --universe nifty200 --top 20 --ensemble` returns weighted blend, each lens family weight >0, `test_quant_hardening` ensemble weight assert passes.

**Checkpoint B:** `screen --ensemble` weighted, not funnel-ordered; `trace-causal-chain --node UNION_BUDGET_2026_RAIL_CAPEX --max-hops 3` correct.

### Wave C — Lifecycle: Competitive Survival + Never-Prune
**Goal:** Embeddings compete, structural theories survive.

- **Task C1 — `pruning_engine.py` survival**
  - `HALF_LIVES` already seeded; ensure `macro_source_type_to_category` prefix handles `State_Budget_*`; `is_structural_milestone=1 T½ INF` exempt; `CALL prune_decayed_signals()` decays losers via `S(t)=S0*e^{-λΔt}`.
  - Acceptance: `v_ripple_decayed` shows decayed `S(t)` < `S0` except structural.

- **Task C2 — Distill-before-delete**
  - File: `distillation_pruner.py`
  - Monthly batch `[20 YouTube +4 Concalls] → LLM synthesis → UPDATE business_model_profiles/moat_evaluations → purge 24 vectors` → `distillation_runs`.
  - Acceptance: `SELECT * FROM distillation_runs ORDER BY run_date DESC LIMIT 1` correct.

**Checkpoint C:** Prune retains structural; distillation delta applied pre-purge.

### Wave D — MoE + Transient Graph + EOD Corrector (brain/transformer)
**Goal:** Sparse, revisable reasoning.

- **Task D1 — `ensemble_ranker.py` MoE**
  - Table `model_explainer_rankings(stock_id,sector_id,geo_id,regime_tag,investor_majority∈{promoter,FII,DII,retail},lens_family,p_value,explain_power,rank)` + `lens_activation_log(temperature,fired_lenses)`.
  - Temperature controls explore (mutate pathway) vs exploit (consolidate); `explanation_weight ↑/↓`.
  - Acceptance: `rank-models --symbol HAL --investor-majority FII` queryable; `lens_activation_log` audit per run.

- **Task D2 — `event_graph.py` transient spawner**
  - Example `US_TARIFF_TEXTILE_RELIEF`: parse %/date/exceptions/conditional US plant → fetch remotely active dyes/yarn/cotton + machine-makers (2nd-order fwd/back) → quantize `30% hit→30% recovery`, `lag_time_months` → `ripple_effects`.
  - Acceptance: `spawn-event-graph --event US_TARIFF_TEXTILE_RELIEF --max-hops 3` finds primary ≠ biggest beneficiary; Pydantic `MacroEventExtraction` transactional.

- **Task D3 — `eod_corrector.py` self-correction**
  - Cadence `EOD price + FII/DII + major event` (NOT intraday), per-scrip noise floor learned, re-ranks lenses, mutates embeddings, updates substrate.
  - Acceptance: `correct-eod --universe nifty200` re-ranks; `noise-floor --symbol TITAGARH` returns value; `correct-event --event ...` revises 2nd-order graph.

- **Task D4 — Orchestrator + reporting**
  - File: `agent/orchestrator.py`, `reporting/writer.py`
  - Synthesize multi-lens thesis → JSON/MD/HTML; CLI `run-daily-alpha --top-theses 5 --ensemble`, `inspect-stock HAL`.
  - Acceptance: `test_agent_and_reporting` + `test_cli_and_dashboard` pass.

**Checkpoint D (final):** 103→~110 tests OK; `rank-models`, `spawn-event-graph`, `correct-eod`, `run-daily-alpha` all succeed; dashboard 6-tab shows MoE/ensemble.

## 3. Fresh Session Bootstrap Commands (run in order)

```bash
# 0. Verify inbound data still intact
python -m unittest discover -s reality_engine/tests -p "test_*.py"  # expect 103 OK
python reality_engine/cli.py fetch-macro --source all --years 2024-25,2025-26 --dry-run  # 24 planned
python -c "from reality_engine.db.repository import repo; from reality_engine.db.database import db_manager; print('raw',len(repo.list_raw_documents_by_source(''))); import pathlib; print(list(pathlib.Path('reality_engine/data/macro_pdfs').rglob('*.pdf'))[:3])"

# 1. Wave A — distill macro → substrate
python -m unittest reality_engine.tests.test_distillation_macro -v

# 2. Wave B — ensemble
python reality_engine/cli.py screen --universe nifty200 --top 20 --ensemble
python reality_engine/cli.py trace-causal-chain --node TATASTEEL --max-hops 3

# 3. Wave C — lifecycle
python reality_engine/cli.py prune-decayed-signals --dry-run

# 4. Wave D — MoE + transient + corrector
python reality_engine/cli.py rank-models --symbol HAL --investor-majority FII
python reality_engine/cli.py spawn-event-graph --event US_TARIFF_TEXTILE_RELIEF --max-hops 3
python reality_engine/cli.py correct-eod --universe nifty200 --dry-run
python reality_engine/cli.py run-daily-alpha --universe nifty200 --top 20 --top-theses 5 --ensemble
```

## 4. File Ownership (avoid parallel conflicts)

- Wave A: `distillation_engine.py`, `business_profiler.py`, `moat_scorer.py` (no overlap)
- Wave B: `policy_engine.py` | `causal_engine.py` | `composite_screener.py` (separate)
- Wave C: `pruning_engine.py`, `distillation_pruner.py`
- Wave D: `ensemble_ranker.py` | `event_graph.py` | `eod_corrector.py` | `orchestrator.py`

## 5. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| GJ 0 docs, KA 2024-25 0 | Treat as missing peer — ensemble handles partial data (dense substrate even if incomplete is the ballgame, per AGENTS.md). Log gracefully, do not block. |
| Per-scrip noise floor mislearned | Backtest vs realized vol, clamp floor, checkpoint B. |
| MoE temperature mistuned | Audit `lens_activation_log`, A/B temp, checkpoint D. |
| Vector bloat | Partitioned `document_chunks`, competitive pruning, distill-before-delete. |
| LLM lens hallucination | Enforce Pydantic schemas.py, transactional repo writes, no free-text graph. |

## 6. Definition of Done for Next Session

- [ ] All macro chunks distilled → `macro_events`/`ripple_effects` with %/date/exceptions quantized
- [ ] 4 peer families queryable, weighted ensemble `screen --ensemble` returns blended ranks with noise floor
- [ ] `pruning_engine` decays losers, retains `is_structural_milestone=1`
- [ ] `rank-models` per investor-majority, `spawn-event-graph` 2nd-order correct, `correct-eod` re-ranks, `run-daily-alpha` thesis exported
- [ ] 103→110 tests OK, no ISIN drift, SQLite fallback intact

## 7. Open Questions (human input if blocked)

- Ensemble weight bootstrap before EOD batches: heuristic vs learned?
- MoE temperature schedule fixed vs annealed?
- Investor-majority proxies availability for retail?

*Save point: do not re-run macro fetch unless `data/macro_pdfs` was cleared. Next session starts at Wave A.*
