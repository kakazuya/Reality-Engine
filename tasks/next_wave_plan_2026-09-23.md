# Session Findings + Next Wave Plan — 2026-09-23

> Read-only investigation pass over the live DB, the tracker, and the code. **No source file was
> modified by this pass**; the only edits are this document and the tracker correction disclosed in §7.
>
> Supersedes the P1–P7 ordering in `tasks/modeling_bucket_list.md` for **sequencing only** (the ideas
> stand; the order changes). Corrects the promotion recorded in `tasks/strategy_tracker.md` on 2026-09-22.
>
> **Objective served:** cause→effect attribution — explain WHY price moved from available information,
> isolate the residual as mispricing, drive cash-segment BUY/SELL/HOLD for return on capital.

---

## 0. Verdict in one paragraph

The warehouse, substrate, ledger, ensemble, and nightly loop all exist and run. But every layer that
was supposed to *measure* something is measuring something else: the book's SELL exits are sign-inverted
(its "46/46 wins" are an accounting artifact), the bracket is a fixed 18%/6% for every name regardless
of volatility, the residual is a constant ≈0.89 because three of four lenses return 0 by design, the
level tables have no time axis at all, and the benchmark maps 84% of the universe to Microcap 250.
Two consequences dominate: **no strategy in the tracker can be promoted on current evidence**, and
**the cheapest fix for that (extending the window) is unsafe as scripted** because the pipeline is not
point-in-time. The plan below reorders everything behind four honesty pillars — book, yardstick, time,
evidence base — and identifies one measurement that is already runnable, read-only, and needs nothing
that is currently blocked.

---

## 1. Live state (verified 2026-09-23 ~01:00, not from docs)

| Thing | Reality |
|---|---|
| Drain | `ingest-annual-90b` alive, 93/2184 docs, 22–36 s/doc → **~15–18 h** of GPU + single SQLite writer left |
| Drain failures | `ingestion_queue.log`: `drhp` stage crashed **18×** with `exit=3221225477` (**0xC0000005 access violation** — native crash in the PyMuPDF/RapidOCR/onnxruntime path under GPU contention), then `exit=0` on attempt 3. The four dead `ingest-annual-*` runs were **superseded duplicates**, not wedged writers |
| Prices | frozen at **2026-09-18**; `sec_bhavdata_full_21092026.csv` + `sec_bhavdata_full_22092026.csv` **on disk, un-ingested** |
| Book | BUY 44 closed (1 win, −5.00 mean) / 121 open; SELL 46 closed / 6 open (all 2026-09-18); HOLD 495 closed / 151 open |
| Book P&L | BUY **−219.87**, SELL **+249.67** → the "+29.8 first profit" is entirely the SELL artifact (§2A) |
| Ledger | `move_attribution` 136,642 rows / 60 dates (2026-06-29→09-18) / 43,789 material; `eod_scrip_calls` 5,139 rows (60 dates, 401 symbols) |
| Substrate | chunks 748,315 · macro_events 30 · ripple_effects 61 · model_explainer_rankings 69,500 · quarantine 1,377 · moat_evaluations 2,653 (covers only **52%** of material rows) |
| History depth | prices 1,265 dates 2021-10-27→2026-09-18; **nse_index_breadth 262 dates 2025-09-01→2026-09-21**; attribution & call rows only 60 dates |
| Benchmarks | only **50** masters `is_nifty50=1`; **5,909** tier MICRO (default bucket); 101 LARGE non-Nifty50 silently dropped as `unmapped-universe` |

---

## 2. Findings (evidence, not narrative)

### A. The promoted SELL leg is an accounting artifact
- **Terms layer:** all **52** SELL rows carry `target_price > entry_price` — long-framed. `eod_scrip_calls`
  is mechanically long-framed for **all 5,139 rows** (`target = price × 1.18`, `stop = price × 0.94`);
  **0 of 5,139** have `target < price`; `risk_reward_ratio` has only **7 distinct values (2.96–3.04)**.
- **Exit layer:** `portfolio_ledger.mark_to_market` mirrors triggers for SELL (`stop_hit = high >= stop`).
  With a long-framed stop *below* entry that fires on **bar 1, always**, and
  `pnl = −1 × (stop/entry − 1) = +|stop%|` books a stop-out as a gain.
- **Data:** **46/46** closed SELLs have `exit_price == stop_loss`, `pnl` exactly `|stop%|`
  (6.48, 7.42, 5.32, 4.96 …), days = 1 (3 over weekends).
- **Tracker number:** `+527bps, n=34, hit 1.00` reproduces **only** with the book's `exit_price` as the
  fill (measured **+553bps, hit 1.00**). On market closes over the same windows: **−20bps, hit 0.50**.
- **Provenance is clean:** 0 of 5,139 call rows have `created_at < date` — no hindsight. The defect is
  framing, not timing.

### B. The whole book measures a fixed 18%/6% bracket, not the lenses
**43 of 44** closed BUYs exited at `stop_loss` (1 at target), median ~12 sessions. So "BUY 1/44, mean
−5.00" is the verdict on *"does a name dip 6% before it rises 18% within 60 sessions"* — bracket
geometry — not on residual/quality/policy/supply lenses.

### C. Quarantine does not gate book/ledger reads (AGENTS.md §13)
`substrate_quarantine` covers `master_companies` (1,356 synthetic `INE_AUTO_*`), graph nodes/edges, demo
macro/ripples — **no book or ledger table**.

| Table | Rows joining a quarantined master |
|---|---|
| `move_attribution` | **4,770** (LOWVOL1, VALUE, SBILIQETF, SILVERBND, GROWWGOLD, AAREYDRUGS, IFBAGRO) |
| `eod_scrip_calls` | **7** |
| `portfolio_actions` | **0** — clean only *incidentally* |

`seed_track_record.run_seed` has **no quarantine join**. **G3: never delete `INE_AUTO*` rows** (designed
backfill-stub stage) — exclude them from inference reads only.

### D. Drain failure mode
Repeated `0xC0000005` access violations under GPU contention (18 attempts, then success). Operational
rule: **never co-run a second GPU/DB job with the drain.**

### E. Substrate depth is hollow
- `graph_causal_edges` = **15 rows** (9 production + 6 quarantined `TEST_*`) vs D3's ~31,106 estimate.
- Peer graph: 50,180 pairs / 4,996 features; **12 of 29 features active**. HAL's nearest "analogues" are
  DIVISLAB / ITC / SUNPHARMA (market-cap twins), not defence names.
- **D2 verified live** (`company_distilled_parameters` EAV: `parameter_key` + `value_json`):

| Field | Degeneracy |
|---|---|
| `is_cyclical` | 3,332/3,474 = **95.9%** zero |
| `cycle_duration_years` | 3,323/3,474 = **95.7%** = 10.0 |
| `stage_conviction` | 3,423/3,474 = **98.5%** = 0.6 |
| `moat_rating` | 3,067/3,573 = **85.8%** = 4 |
| `n_revenue_drivers` | **0 non-null** |

…while the same `value_json` prose (`cyclicality_type`, `cycle_current_stage`, `key_revenue_drivers`) is
rich and per-company. **The substrate kept a constant as the number and dumped the signal into free text.**
- O2 verified landed (no `value-creative` / `ROIC-WACC` in generated reports). G1: the
  `business_model_profiles_demo` mirror now has no reader. G2: never re-point `_lookup_roic_wacc_spread`
  (2,414/2,585 canonical rows are the default −0.1).

### F. The attribution metric is degenerate; 3 of 4 lenses are mute
Material rows n = 43,789:

| Measure | Value |
|---|---|
| Mean `explained_total` | **0.110** |
| Mean `residual` | **0.890** |
| Rows with `explained_total = 0` | **22,423 (51%)** |
| Rows with `explained_total > 0.5` | **0** (histogram: 0.0→22,526 · 0.1→4,293 · 0.2→6,061 · 0.3→10,899 · 0.4→**10**) |
| Rows where quality / policy / supply emit a non-zero direction | **0 / 0 / 0** |
| Rows where factor emits a direction | **42,346** |
| Ledger mean weights | supply 0.358 + quality 0.271 = **63% on lenses that never vote**; factor 0.226 |
| `regime_tag` | `'*'` on **100%** |
| `investor_majority` | promoter 61% · all 29% · retail 8% · **FII 1.8%** |

Because `share = w × 1{pred == sign(realized)}`, `explained_total` can never exceed the summed weight of
agreeing lenses — so the action table's `residual > 0.5` condition is **true for 100% of material rows**,
and the BUY/SELL decision reduces to `sign(realized) × quality_intact × solvency`. The learning loop
disagrees with the ledger: `model_explainer_rankings` mean `explain_power` says `supply_chain` is the
best explainer (0.4438).

### G. Root cause of the mute lenses
`eod_corrector` predictors, verified in code:
- `_predict_factor` = `sign(prev-day change_pct)` — **the only voter** (momentum).
- `_predict_quality(symbol, asof_date)` — dated branch **returns 0 ALWAYS** ("`moat_evaluations` carries
  no history/version column").
- `_predict_policy(symbol, asof_date)` — dated branch **returns 0 ALWAYS** ("no versioned revisions per
  (ticker, policy)").
- `_predict_supply(symbol, asof_date)` — votes only on same-session ripple arrivals; with 61 ripple rows
  it never does (0 of 43,789).

**One root cause, three symptoms:** mute lenses (F), degenerate residual (F), and calibration
`applied=false` on every run (`skill_loop.run_folds` has no per-lens edges to fit).

### H. The level tables structurally have no history
- `moat_evaluations`: **exactly 1 row per ticker** (2,653) — `eval_date` is batch-write time.
- `regulatory_political_risks`: **exactly 1 row per (ticker, policy_name)** (5,470) — no revisions.
- `ripple_effects`: 61 rows, 4 distinct `created_at` dates.
- **Dated evidence exists one layer down:** `raw_documents` 6,523 docs, **613 distinct published dates**,
  2021-01-20→2026-09-21 (2026-08 = 5,405 docs / 234,671 chunks; 2026-09 = 218 docs; 2026-06/07 = 8/10).
- **Vacuous gates:** `residual > 0.5` (100%), `solvency_ok` (`is_solvency_approved = 1` on **all 5,139**
  call rows), trajectory clause (Stable 2,646 / Expanding 6 / Deteriorating 1). Live inputs are only
  `sign(realized)`, `moat < 2.5` (949/2,653 = 36%), dislocation ≥2σ, factor agreement.
- `quality_intact` **fails OPEN to `True`** on any exception in the resolver.

### I. The suite bets against its own only regularity (provisional — see §3)
Index-relative forward excess, material rows, 60 sessions: after **UP** 1s +0.23% / 5s +0.55% / 20s
−0.07%; after **DOWN** 1s −0.02% / 5s −0.50% / 20s −1.43%. Market-neutral, up-movers modestly
**outperform** down-movers at 1–5 sessions: the regularity is short-horizon **momentum continuation**,
not reversal — while the action table bets on reversal. The only live lens: hit **0.533** at 1s, +0.45%
gross → **−0.05% net of the 50bps round trip**; 5s mean +0.91% but median −0.17% (net −0.67%).

### J. Cell-level forward test (provisional)
Index-relative: the BUY cell (DOWN) ≈ 0 at 1s and negative at 5/20s; **every cell negative at 5 and 20
sessions** (−1.19% … −3.13%, P(>0) 0.33–0.38) — a uniform negative drift that is a **benchmark-artifact
signature**, not a market fact.

### K. Cross-sectional control changes the readings
Measured benchmark bias: index-relative carries **~0.4–1.0pp** of negative bias at 20 sessions (smaller
than an initial 1–3% estimate — corrected). Under a same-day cross-sectional control, unmatched: BUY
cells −0.44…−2.17%; SELL short-side +0.38…+1.12%. Matched control (moat-covered population): UP broken
+0.40% / UP intact −0.15%; DOWN broken +0.13% / DOWN intact −0.09%.

### L. Retraction + power (this one governs all the others)
- **The "inverted quality clause" claim is withdrawn.** Broken − intact flips sign across noise-floor
  quintiles: UP q1 −1.59pp · q2 **+2.04** · q3 +0.39 · q4 −0.13 · q5 +1.45; DOWN q1 −0.19 · q2 +1.14 ·
  q3 +0.10 · q4 −0.88 · q5 +1.02. The pooled +0.2…+0.55pp is the average of a sign-flipping contrast.
- **The 20-session tests are underpowered by ~an order of magnitude.** Matched sample = 40 dates =
  8 ISO weeks → **≈2 independent 20-session cohorts**. "Hit 1.00", ±0.1pp means, and P(>0) to three
  decimals are illusory — in the tracker *and* in the measurements above.
- **Extendable bound:** index breadth starts 2025-09-01 → 262 sessions ≈ **13 independent 20-session
  cohorts / ~52 weekly cohorts**. The promotion bar must be stated per horizon.

### M. The pipeline is not point-in-time — the obvious fix is unsafe as scripted
`composite_screener._lookup_moat_metrics(symbol, isin)` and `ensemble_ranker.get_ensemble_weights_for_context`
take **no date/asof key** (context = stock/sector/geo/regime/investor only); moat and policy are
single-snapshot. So backfilling call rows for 2025-09→2026-06 and re-running attribution would stamp
**today's** substrate onto the past — a look-ahead machine. The existing 60-date ledger is already
snapshot-contaminated, invisibly, because the substrate is single-snapshot and three lenses are mute.
**P0b must ship with point-in-time reads, not before them.**

### N. The highest-value measurement is unblocked, read-only, and needs no backfill
Verified `move_attributor`'s full dependency set: `daily_price_delivery`, `master_companies` (symbol
list), `company_forensic_health` (static), the `EODCorrector` predictors, and the ranker weights — which
**fall back to static `BOOTSTRAP_ENSEMBLE_WEIGHTS` = {factor 0.30, quality 0.25, policy 0.25, supply 0.20}**.
So an honest, point-in-time attribution run needs **only prices + static bootstrap weights + the
price-only factor predictor**: no call rows, no screener, no substrate read, no writes, no look-ahead.

A first load confirms the scale: prices from 2025-09-01 give **755,494 rows / 5,223 symbols / 274 dates**,
of which **207,152 material rows over 250 dates** (same material definition) versus the ledger's 43,789
over 60 dates — **~4.7× the evidence base, from prices alone.**

---

## 3. What is fact and what is provisional

| Class | Items |
|---|---|
| **Structural facts** (code/data, verified) | A, B, C, D, E, F, G, H, M |
| **Provisional** (readings of ~2 independent cohorts; L governs) | I, J, K — and one of these (the quality-clause inversion) is **already retracted** |
| **Unblocked measurement** | N — the spec below, read-only, no backfill |

---

## 4. Plan — four honesty pillars, then strategy work

| Pillar | Work | Gate |
|---|---|---|
| **Honest book** (code) | SELL framing invariant (`target < entry < stop`, asserted at write); vol-scaled per-scrip bracket; quarantine predicate in seed + every book read; `solvency_ok` non-vacuous; fail-open `quality_intact` closed | No SELL `exit == stop`; solvency gate rejects something |
| **Honest yardstick** (query/data) | same-day cross-sectional control matched on the same population; universe map fixed (2,093/2,481 → Microcap 250 today) | Excess stable under the control; ≥80% of symbols on the right benchmark |
| **Honest time** (discipline) | `asof` / `valid_from` on substrate reads; historical extension uses **price-only terms** so nothing leaks | A historical re-run replays identically using only data available at that date |
| **Honest evidence base** (batch) | ingest 09-21/09-22 (on disk); extend to the index-breadth bound (2025-09-01) → ~13 independent 20-session cohorts / ~52 weekly | ≥13 cohorts at 20 sessions; bar stated per horizon |

### Phases

| Phase | Deliverable | Status |
|---|---|---|
| **P1** premise grid (read-only) | the §6 spec over 262 sessions: continuation vs reversal × 1/5/10/20/40/60 × regime × universe, XS control, vol-stratified, cohort-clustered, shuffle placebo | **runnable now** — nothing blocked |
| **P0** book + yardstick + time | the three pillars above; ingest 09-21/09-22 staggered after a drain checkpoint | code work safe now; ingest waits |
| **P0b** peers speak | dated deltas from `raw_documents`/`document_chunks` (dated, dense Aug–Sep) for quality/policy; same-session ripple stamping for supply; **ships with point-in-time reads** | ≥2 lens families vote; `residual` gains variance; folds have edges to fit |
| **P2** selection | forensics veto (Beneish/Altman/Piotroski/accruals); quality clause re-tested **vol-stratified, not inverted**; BUY leg parked until P0b | Clause direction established, not assumed |
| **P3** conditioning | India VIX regime; GARCH(1,1) floors; investor-majority (FII conditioning is 1.8%) | Excess by VIX quintile |
| **P4** sizing/exit | OU half-life exits, fractional Kelly, EVT stops — only for a leg past the bar | Bar met in both regimes, placebo ≈ 0 |
| **P5** infra | drain scoping decision, slippage audit, serial-fast suite, `lancedb/vectors.json` reclaim; D1 dossier→inference (ctx 4096 ≈ 2 symbols); D2 re-distill targeting the *varying* prose fields; D3 edge extraction (explicit cloud-vs-local call) | opportunistic |

### Promotion bar (replaces the single-line bar; stated **per horizon**)

1. Cohort-clustered mean excess ≥ **+500bps** net of **measured** (not assumed) costs.
2. **≥30 weekly cohorts** at short horizons, **≥13** for 20-session holds; spanning **≥2** index regimes.
3. Hit-rate CI **lower bound > 0.5** (cluster-robust, not trade-level).
4. Same sign in both regimes.
5. **Falsification:** shuffle-entry-date placebo on the same names gives ≈ 0.

Also: `summarize()` blends positional pnl-wins with 0.5-scored HOLD agreement into one `win_rate`
(0.51) — never quote that as a hit rate.

---

## 5. Open decisions (human input)

1. **Drain scope** — all 2,184 annuals (~15–18 h of the single writer), or a top-N-symbol slice first?
2. **Bracket rule** — GARCH(1,1) conditional vol, or trailing-σ percentile, and what clamp?
3. **Fill convention** — close-through-the-level as default (touch-fill as a labelled sensitivity), or
   keep touch-fill and haircut?
4. **SELL scoring** — avoided-loss-vs-holding (recommended: cash-segment honest), or short excess?
5. **Point-in-time discipline** — schema `valid_from` columns, or a read-layer `asof` parameter?
6. **Universe mapping** — add Nifty 100/200 membership, or keep 4-universe mapping + printed coverage?
7. **D3** — cloud batch ($5.22–$86.98) vs the local-only/no-cloud stance.

---

## 6. P1 spec (read-only; the measurement to run first)

1. **Population:** every (symbol, date) in `daily_price_delivery` from 2025-09-01 (index-breadth bound).
2. **realized / material:** close-to-close %; floor = trailing-20-session σ clamped [0.5, 8.0] (same rule
   as the ledger); `is_material = |realized| > floor`.
3. **Lens directions:** factor = `sign(prev-day change)`; quality/policy/supply = 0 (honest — no history).
4. **Weights:** static `BOOTSTRAP_ENSEMBLE_WEIGHTS` — **never** current rankings (that would leak).
5. **Forward excess:** 1/5/10/20/40/60 sessions; **cross-sectional control (same-day mean of the same
   population)** primary, index-relative secondary for comparison.
6. **Stratify:** noise-floor quintile × dislocation (≥2σ) × realized sign × ISO-week cohort × universe
   (with the map caveat).
7. **Report:** cohort counts per cell, mean/median excess, hit rate with cluster-robust CI, and a
   shuffle-entry placebo.

---

## 7. Disclosure — edits already applied before the "do not edit" instruction

1. **New file:** this document (`tasks/next_wave_plan_2026-09-23.md`).
2. **Edited `tasks/strategy_tracker.md`** — 5 regions: header line; the promotion-bar rule line; the T4
   and T5 rows (→ ARTIFACT / REVOKED); a 2026-09-23 REVOKED row in the promotion log with the
   2026-09-22 PROMOTED row struck; and the improvement backlog (blockers 0/0b/0c prepended, list
   renumbered 1–8).

Verbatim originals for a one-step revert of the tracker:

```
L3: > Last updated: 2026-09-22 late (book v5: 863 actions, 585 closed, win 0.51, pnl +29.8; SELL realized-window +527bps n=34; BUY still failing)
L4: > Rule: update this file after every strategy test (result + evidence + next). Promotion bar: walk-forward folds + `apply_if_improved` fires + net excess ≥ +500bps vs universe index net of 50bps.
T4: | T4 | SELL widened broken-thesis: Deteriorating OR moat<2.5 OR ENI<0 | Unexplained strength in broken-quality names mean-reverts | `seed v5`: 52 SELL seeded | 46 closed, **46/46 wins +3.5–7.4%**; next-day down 32/46 | ✅ PASS | Expand sample past 46; test longer holds (OU half-life exits) vs 1–7d target exits |
T5: | T5 | SELL realized-window excess vs universe index | Short-notional window return − index same-window − 50bps | `tasks/check_sell_excess.py` (removed after run); `excess_table_v5/v6` | **n=34, mean +527bps, median +513bps, hit 1.00**, 6 weekly cohorts | ✅ PASS (gate met) | Small/micro cells n=0 — needs call-row coverage there, not more nifty/midcap |
LOG: | 2026-09-22 | SELL widened broken-thesis + realized-window excess | 46/46 wins; +527bps n=34 hit 1.00, 6 cohorts | PROMOTED to gate-passing leg |
BACKLOG: the original seven items (BUY −500bps / small-micro n=0 / SELL holding periods / calibration / substrate versioning / slippage audit / test-suite speed)
```
