# Desk Backtest + Calibration Harness — 2026-09-25

> Objective: Mumbai prop-desk edge verdict + ₹10cr book maximization with minimal drawdown.
> Ground truth: `tasks/SESSION_HANDOVER_2026-09-25.md` + `tasks/test_findings_2026-09-24.md` §§1–14
> + `tasks/strategy_tracker.md` + `tasks/next_wave_plan_2026-09-23.md` §4 pillars + §6 P1 spec + §5 promotion bar.
> Non-goal: **no ledger rewrites** (this doc is spec + shells only; no `portfolio_actions`/`portfolio_ledger`/`eod_scrip_calls` mutation).

## 0. Guardrails (inviolable)

- REVOKED artifacts — never regress: SELL +527bps (sign-inverted stop-as-gain), blended +29.8 profit,
  confirmation filter (1W/29L), trend-continuation entry (6/34). Any recompute reproducing these shapes
  (e.g. SELL `exit_price == stop_loss` ≈ 100%, days=1) FAILS the harness, not the strategy.
- Denylist: never edit `reality_engine/db/repository.py` or `schema.sql`; no live-row deletes;
  no `git stash`; no destructive ops; no new packages. Additive schema only; quarantine joins on reads.
- Single SQLite writer + queue lock; never co-run GPU/DB jobs (drain `0xC0000005` history).
- Capital: **₹10cr cash, Oct 2021** (lump sum; distinct from the ₹1L+50k SIP frame in `sip_backtest.py`).
  May hold cash/gold/silver up to **40%** when not ROI-positive (sweep rule §1.7).
- Costs: **50bps impact prior + STT 0.1%/side + STCG 20% / LTCG 12.5% (>365d; exactly-365d = short)**
  per Finance (No. 2) Act 2024 + tax harvesting + measured slippage (see §1.8). Never assume costs away.
- Promotion bar (per horizon): cohort-clustered mean excess **≥ +500bps net of measured costs**,
  **≥30 weekly cohorts** (≥13 for 20D holds), spanning **≥2 index regimes**, hit-rate CI lower **> 0.5**
  (cluster-robust), same sign both regimes, **shuffle-entry placebo ≈ 0**.

## 1. Backtest spec — ₹10cr, Oct 2021, honest

New runner (proposed): `reality_engine/processing/desk_backtest.py`, reusing `sip_backtest.py`
price/tax conventions (close-usable iff finite > 0 from `daily_price_delivery`; trade at closes only;
no forward-fill for trading; valuation carries last close on/before date; FIFO lots; FY LTCG exemption
tracking; no cross-year loss carry-forward; risk-free 0). SIP schedule does NOT carry over — lump-sum
₹10,00,00,000 cash at 2021-10-27; no leverage (buys scaled to cash; uninvested sits at 0%).

### 1.1 Population bulletin (point-in-time)

1. Universe: every (symbol, date) in `daily_price_delivery` from **2021-10-27**; signal-evaluation
   window gated by `BREADTH_START = 2025-09-01` for the XS-control leg (breadth 262 sessions bound).
2. Quarantine predicate on EVERY read: exclude `INE_AUTO_*` / quarantined masters
   (`move_attribution` carries 4,770 tainted rows, `eod_scrip_calls` 7 — AGENTS.md §13).
3. No second convention beside the existing price convention: close-usable rule mirrors
   `sip_backtest.py:11-15` and `portfolio_ledger.horizon_excess` exactly.

### 1.2 Terms — price-only, point-in-time (P0b discipline)

4. Lens directions: factor = `sign(prev-day change_pct)` (the only genuine flow); quality/policy/supply
   = **0** unless a **dated delta** exists (`moat_history`/`policy_eni_history`/`ripple_history` with
   `asof_date ≤ entry_date`; downgrade/drop = −1, upgrade = +1; `asof_date=None` keeps legacy gate-only
   behavior per `eod_corrector.py:34-51`). Levels (moat/ENI/significance) GATE, never VOTE (T2).
5. Weights: static `BOOTSTRAP_ENSEMBLE_WEIGHTS` = {factor 0.30, quality 0.25, policy 0.25, supply 0.20}
   (`composite_screener.py:63-66`, `ensemble_ranker.py:50-53`). **Never** current learned rankings /
   `get_ensemble_weights_for_context` / `_lookup_moat_metrics(symbol, isin)` without an asof key —
   that path is snapshot-contaminated (plan §2M) and fails the harness on sight.
6. Materiality: `realized` = close-to-close %; floor = trailing-20-session σ clamped **[0.5, 8.0]**;
   `is_material = |realized| > floor` (same rule as the ledger; P1 §6.2).
7. Entry thesis (gated BUY/SELL only): dislocation **≥ 2σ** + factor agreement + intact quality +
   solvent (T3/T6). Sub-2σ entries demote to HOLD. Lone-residual BUY stays dead (T1).
8. SELL framing invariant (asserted at write, P0): SELL ⇒ `target < entry < stop`; BUY mirrored;
   HOLD levels None. Any SELL row violating this aborts the run.

### 1.3 Brackets — vol-scaled (blocker 0b fix)

9. Per-scrip bracket from trailing-σ (or GARCH(1,1) when P3 lands), clamped; expected post-P0 shape:
   BUY widths ≈ 11.87–22.93% (61 distinct), SELL mirrored ≈ 2.31–4.79% at 3:1 risk unit.
   Fixed 18%/6% for all names is FORBIDDEN (that geometry produced 43/44 BUY stop-outs, median ~12 sessions).
10. Fill convention: **close-through-the-level** default; touch-fill as labelled sensitivity only (open decision
    §5.3 resolved here: default close-through; report both).
11. SELL scoring: **avoided-loss-vs-holding** (cash-segment honest; recommended) primary; short excess
    secondary (open decision §5.4 resolved here).

### 1.4 Forward measurement — realized window + XS matched control

12. Horizons: **30/90/180/365** sessions for the desk book (P1 1/5/10/20/40/60 retained for the premise grid only).
13. Primary: **same-day cross-sectional control on the same population** (matched on moat-covered population
    where quality splits are read). Secondary: index-relative, for comparison only (carries ~0.4–1.0pp
    negative bias at 20 sessions; uniform-negative-drift = benchmark-artifact signature).
14. Universe map fixed before reads: 2,093/2,481 → Microcap 250 today is a mis-map; print per-universe n +
    unmapped list with every table (backlog 7). ≥80% of symbols on the right benchmark is the gate.
15. Realized-window exit: `min(close, entry+horizon)` (T9); stop/target dates score the realized window,
    not a hypothetical hold. All-horizons-identical output = diagnostic flag, not a result.
16. Stratify: noise-floor quintile × dislocation × realized sign × **ISO-week cohort** × universe ×
    VIX quintile (when P3 lands) × investor-majority (FII conditioning noted thin at 1.8%).

### 1.5 Cohorts, inference, placebo (promotion bar wiring)

17. Cohort-clustered stats per cell: n, cohorts, mean/median excess, clustered SE/CI, hit rate with
    **cluster-robust CI** (cohort_hit_ci_lower reported; cf. `p1_grid_nifty50_2026-09-24.json` cell shape:
    `clustered_mean/_se/_ci`, `cohort_means`, `cohorts`, `hit_rate`, `hit_ci_lower`, `cohort_hit_ci_lower`).
18. Bar: ≥+500bps clustered net · **≥30 weekly cohorts** (≥13 for 20D) · ≥2 regimes · hit CI lower > 0.5 ·
    same sign both regimes. P1's 3-cohort cells are the underpowered example that must NOT pass.
19. Falsification: **shuffle-entry-date placebo** on the same names (≈ 0 required; P1 placebos ≈ 0 is the
    honest-gate example). Strategies failing a ≈0 placebo while passing real = reject.
20. `summarize()` positional-pnl + 0.5-scored HOLD agreement blend (0.51) is NEVER quoted as a hit rate.

### 1.6 Forward-OHLC rule (goal-success gate)

21. **≥30 closed BUY/SELL actions with forward OHLC** before any promotion read. New-gate BUYs still open =
    forward sessions must close them first (T3/T6). Backfilled 09-19→09-23 precedent (14,484 rows) noted;
    any forward extension uses price-only terms so nothing leaks (honest-time pillar).
22. Reproducibility: a historical re-run replays identically using only data available at that date
    (asof/valid_from discipline; price-only extension).

### 1.7 Cash / gold / silver sweep (≤40%)

23. When no thesis clears the gates (net-of-cost excess < 0 or cohorts < bar), sweep unallocated capital
    into cash/gold/silver up to 40% of NAV at 0% modeled yield for cash; gold/silver legs marked on their
    own closes with the same cost stack. Sweep fraction and trigger printed on every NAV path.

### 1.8 Cost stack + slippage audit (measured, not assumed)

24. Per round trip: impact 50bps prior + STT 0.1% buy + 0.1% sell + `OTHER_CHARGE_RATE` 5bps assumed prior
    (flagged) + FIFO STCG 20% / LTCG 12.5% above ₹1.25L/FY + harvesting rule (realize losses within-FY;
    no cross-year carry-forward modeled). Slippage audit (backlog 6) shrinks the 50bps prior with data.

## 2. 4×4 excess shell — 30/90/180/365 × Nifty50 / Midcap150 / Smallcap250 / Microcap250

> Shell only: shape + rules. Numbers filled by the runner; every cell prints n + cohorts + clustered
> stats + placebo, plus the unmapped-symbol list. No cell promotes below the §0 bar.

```
rows = horizons [30, 90, 180, 365]      cols = universes [Nifty50, Midcap150, Smallcap250, Microcap250]
per cell: { n, cohorts, clustered_mean_bps, clustered_ci, hit_rate, hit_ci_lower, cohort_hit_ci_lower,
            placebo_mean, placebo_ci, placebo_delta, by_regime { uptrend/drawdown: same fields } }
coverage footer: per-universe n + unmapped list (LARGE non-N50 etc.) + quarantine-excluded count
```

| Horizon \ Universe | Nifty 50 | Midcap 150 | Smallcap 250 | Microcap 250 |
|---|---|---|---|---|
| 30 | n=· cohorts=· mean=·bps CI=[·,·] hit=· (CI lo ·) \| placebo · | · | · | · |
| 90 | · | · | · | · |
| 180 | · | · | · | · |
| 365 | · | · | · | · |

Rules: XS-matched primary; index-relative secondary column-pair for comparison; realized-window exits;
close-through fills; SELL avoided-loss primary; sweep-aware NAV; placebo per cell; ≥30 cohorts (≥13
tolerated only for 180/365 with stamped caveat + ≥2 regimes).

## 3. Calibration plan — folds logged with apply-gate

1. Folds predate the SELL book → re-run after P0 on the v5+ book with SELL regime represented (backlog 4).
2. `run-calibration` logs every fold (edges fitted per lens; starved single-voter folds stay `applied: false`
   — that refusal is healthy, cf. test-findings §3). Weights move ONLY on out-of-sample improvement
   (`apply_if_improved`); all `applied: false` runs stay logged, never deleted.
3. Gate for un-muting: signal-audit re-run shows quality/policy/supply direction counts > 0 on material
   rows (baseline 0/0/0; SBIN-quality + supply-25 = mechanism proven, breadth pending). No strategy
   benchmarked against the residual until the gate flips.
4. If batch folds keep refusing, consider the bandit (online) alternative — as a labelled experiment,
   not a silent substitution. P4 sizing/exits (OU half-life, fractional Kelly, EVT stops) unlock ONLY
   for a leg past the bar, in both regimes, with placebo ≈ 0.

## 4. Verification commands (scoped proof; no project-wide suites)

```powershell
# Doc exists + shell/plan present
ls tasks/desk_backtest_2026-09-25.md
Select-String -Path tasks/desk_backtest_2026-09-25.md -Pattern 'placebo|4×4|apply-gate|forward OHLC|BOOTSTRAP|quarantine' | Measure-Object
# Live bounds (read-only; writer must be FREE: hub ps + queue lock)
python -m reality_engine.cli db-status
sqlite3 reality_engine/data/equity_intelligence.db "SELECT max(date) FROM daily_price_delivery; SELECT count(*) FROM portfolio_actions WHERE status='closed';"
# P1 artifact shape reused by the harness
python -c "import json; d=json.load(open('reality_engine/data/reports/p1_grid_nifty50_2026-09-24.json')); print(list(d['cells'].keys()))"
# Scoped regression proof only (no full suite / linters / formatters)
python -m pytest reality_engine/tests/test_sip_backtest.py -q
git status --porcelain   # expect ONLY tasks/desk_backtest_2026-09-25.md
```

Expected: doc present with all §4 keywords; EOD max ≥ 2026-09-24; P1 keys include `Nifty 50`;
33 SIP tests green (tax-boundary guard); working tree shows only this file (no ledger/schema churn).
