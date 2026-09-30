# Next Wave — Attribution Close-Out (2026-09-22)

**Objective served:** cause→effect model — explain why prices moved from available
information, isolate the residual as mispricing, drive cash-segment BUY/SELL/HOLD for
return on capital. Data gathering and all prior waves exist only for this.

## 1. State of the tree (verified live this session)

| Layer | Status | Evidence |
|---|---|---|
| Distillation (Ex-A) | Built, thin bulk | `distill_macro_document` + test OK; `macro_events` 30, `ripple_effects` 61 (L1:37/L2:23/L3:1), `distillation_runs` 6 |
| Quality peer (Ex-B) | Built, populated | `moat_evaluations` 2,653, `business_model_profiles` 2,652, `test_moat_backfill` |
| Policy peer (Ex-B) | Built, populated | `regulatory_political_risks` 5,470, `test_policy_eni`, `query_policy_adjusted_screen` |
| Supply peer (Ex-B) | Built | `geographic_exposure` 3,568, `trace_ripple_chain`, `test_supply_chain` |
| Ensemble blend (Ex-B) | Built | `compute_lens_scores` + `compute_ensemble_composite` + learned-weight preference, `test_ensemble_weighted` |
| Lifecycle (Ex-C) | Built | `prune_decayed_signals`, structural-milestone exempt, `test_lifecycle_pruning` |
| MoE ranker (Ex-D) | Built, seeded | `model_explainer_rankings` 69,500 (17,375×4), `lens_activation_log` 1,080, `noise_floors` 201, `test_ensemble_ranker` (hermetic temp-DB) |
| Event graph (Ex-D) | Built | 4 fixture events, `spawn_event_graph` + CLI, `test_event_graph` (hermetic) |
| EOD corrector (Ex-D) | Built | `correct_eod`/`correct_event`, competitive survival ±0.05 cap 2.0, `test_eod_corrector` (hermetic) |
| Harness (validation) | Built, partial | `ValidationHarness.score_predictions`/`fit_lens_weights`/`apply_calibration` (exists, **never called**); `skill_loop.run_folds`/`apply_if_improved`; `model_validation_scores` 224; `eod_scrip_calls` 1,051 with entry/target/SL |
| **Attribution ledger** | **MISSING** | orchestrator: `residual` 0, `explained` 0, `realized` 0, `mispric` 0, `BUY/SELL/HOLD` 0 hits |
| **Portfolio/ROC** | **MISSING** | no position/pnl/hit-rate-action accounting anywhere |

Rankings are **symbol-keyed** (`stock_id` = nse_symbol, `ensemble_ranker.py:630`).
`_norm`: None → `"*"`, investor None → `"all"` — seeded partitions resolve with
`context={"stock_id": symbol}` + optional investor.

## 2. This wave: three slices, one contract

**Slice 1 — Move attribution ledger (foundation).**
New `processing/move_attributor.py` + `tests/test_move_attribution.py`. Own DDL
`ensure_move_attribution_schema()` inside the module (precedent:
`skill_loop.ensure_schema`, `pruning_engine.ensure_pruning_schema`).
NO `repository.py` edits. For each (symbol, date): realized move (close-to-close
pct when `change_pct` absent), noise floor = trailing-20-session population std
of close-to-close % for that symbol, clamped [0.5, 8.0], fallback 2.0 on <5
sessions (CORRIGENDUM 2026-09-22: composite-scale 45.0 floor was unit-wrong;
`is_material = |realized| > floor` in percent points),
per-lens predicted direction by calling `EODCorrector(manager)` predictor
methods (single implementation — do NOT duplicate, do NOT edit eod_corrector),
conditional weights via
`EnsembleRanker(manager).get_ensemble_weights_for_context`, investor via
forensic-holdings-max pattern (`validation_harness._investor_map` pattern,
default `"all"`), regime None (→`"*"`).
Math (exact, no invented magnitudes — O2 lesson):
`share_lens = w_lens × (1 if predicted==sign(realized) else 0)`,
`explained_total = Σ shares ∈ [0,1]`, `residual = 1 − explained_total`,
`is_material = |realized| > floor`. Store ALL evaluated rows with the flag
(nifty200×sessions ≈ 150k rows — trivial).

**Slice 2 — Mispricing → action + thesis (owns `orchestrator.py`, `writer.py`, `cli.py`).**
Reads the Slice 1 ledger (defensive import — works when table empty).
Deterministic 16-cell action table over
(sign(realized) × residual>0.5 × quality_intact × solvency_ok):
unexplained weakness + intact quality + solvent → BUY (panic-alpha bargain);
unexplained strength + broken quality → SELL; explained-aligned → HOLD;
insolvent → HOLD (never BUY — solvency gate from `config.py`:
pledge>15% OR IC<2.5× OR D/E>1.5×). Thesis dict gains `action` +
`attribution{realized_move_pct, noise_floor, is_material, explained_total,
residual, per_lens[{family, predicted_direction, weight, share}],
investor_majority, regime_tag}`; writer renders it in MD/HTML, JSON passthrough.
CLI (sole owner): `attribute-move --symbol --date [--universe-days N]` (single +
batch backfill in one verb), `portfolio-ledger`, `run-calibration` (thin wrappers
over Slice 1/3 entry points, try/except → "unavailable" when modules absent).

**Slice 3 — Portfolio/ROC + calibration feedback (owns `portfolio_ledger.py`,
calls `skill_loop`/`ValidationHarness`, edits neither).**
Own DDL `ensure_portfolio_schema()` in-module. `portfolio_actions(symbol,
action, action_date, entry_price, target, stop, thesis_ref, status)`;
mark-to-market vs `daily_price_delivery` close; close on target/SL/horizon;
aggregates reuse existing `repo.upsert_validation_scores` (no repo edits).
`run_attribution_calibration(manager, mode="ensemble", horizon_days=5)` runs
`skill_loop.run_folds` → `apply_if_improved` so learned weights flow back into
`model_explainer_rankings` (closes the loop: residual → calibration → weights).

## 3. Wave acceptance

- `attribute-move --symbol HAL --date <last closed EOD>` prints realized/floor/
  material + 4×(direction×weight×share) + explained/residual; row persisted.
- Batch `--universe nifty200 --universe-days 25`: `explained_total ∈ [0,1]` on
  every row; median residual < 1.0.
- `run-daily-alpha --top-theses 2` theses carry `action ∈ {BUY,SELL,HOLD}` +
  `attribution` block; writer MD/HTML show it.
- `run-calibration` executes a fold round on live DB: round logged, weights move
  only when improved (`apply_if_improved` gate).
- `portfolio-ledger` shows open actions with MTM vs forward close.
- New tests hermetic (temp-DB precedent); full suite green (parent runs once).

## 4. Risks

| Risk | Mitigation |
|---|---|
| Directional-agreement attribution understates magnitude effects | Documented as v1; shares are fractions of *directional* explanation, never predicted returns |
| 30 macro_events → policy/supply predictors mostly neutral | Ledger shows it honestly via EXPLAIN_FLOOR; calibration down-weights empty lenses |
| Slice 2/3 drift from Slice 1 schema | Exact DDL columns fixed in §2; parent integrates and verifies |
| Single-writer SQLite | Slices write only via their own modules; nightly/loop paused during backfill |
