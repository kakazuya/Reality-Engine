# Desk Quant — Honest Edge Audit + 10cr Book Plan — 2026-09-25

> Owner: DeskQuant-2. Scope: audit `tasks/strategy_tracker.md` T1–T12,
> `tasks/test_findings_2026-09-24.md` §§1,5,6,13, `tasks/next_wave_plan_2026-09-23.md` §2A–2M.
> Output: this file only. No DB/schema edits, no ledger rewrites, no re-seeds.
> Capital frame: **₹10cr cash Oct 2021**, may hold cash/gold/silver up to **40%** when not ROI-positive.
> Costs: **50bps impact** prior (then measured slippage) + STT + STCG/LTCG + harvesting.
> Promotion bar (§5 next_wave_plan, unchanged): cohort-clustered mean excess **≥+500bps net of measured costs**,
> **≥30 weekly cohorts** (≥13 for 20D-class holds; extended below to 30/90/180/365),
> hit-rate CI **lower bound > 0.5** (cluster-robust), **same sign in 2 regimes**, **shuffle placebo ≈ 0**.

---

## 1. TRUE vs REVOKED (ground truth, do not regress)

### 1a. TRUE — what the live tree/DB actually support

| # | Claim | Evidence | Quant meaning |
|---|---|---|---|
| T-1 | **P0 honest book: invariant on write, 0 bad SELLs** | Handover §3; findings §5. Backup `equity_intelligence.pre_p0_20260924_142645.bak.db` on disk. 52 stale long-framed SELLs deleted (46 already scored sign-inverted); backfill rejected. Book 820 rows at reseed (165 BUY / 9 SELL / 646 HOLD), BUY widths 11.87–22.93% (61 distinct), SELL 2.31–4.79% mirrored 3:1, 571 quarantined + 563 non-N50 skipped. **Flow now built: book 841, closed 66** (handover §3). | Framing is now honest going forward. All scored history before the fix stays contaminated — never re-score it in place. |
| T-2 | **P1 grid + placebo: reject / reject** | Handover §3; findings §6. Artifact `reality_engine/data/reports/p1_grid_nifty50_2026-09-24.json` (book 820, EOD max 09-23). BUY n=5 / 3 cohorts, clustered **−328bps**, hit CI lower 0.000 → REJECT. SELL n=7 / 3 cohorts, clustered **+285bps**, hit CI lower 0.116 → REJECT. **Placebos ≈ 0** (gate is honest). Rebuild 09-26 with votes: still reject — real leg immobile, votes don't create actions until flow runs. | Neither leg is near the bar. n and cohorts are ~10× underpowered (3 vs ≥30 weekly / ≥13 for 20D). Placebo ≈ 0 is the one healthy sign: the gate is not leaking. |
| T-3 | **Versioning mechanism proven, breadth thin: SBIN −1 live on-ledger 09-24** | Handover §3; findings §§10,13. N50 recompute 1,250 rows / 406 material (fresh EOD 09-24; `--universe nifty50` branch fix). Quality dirs 0→**1** on-ledger (SBIN 2026-09-24 = −1, share 0.25, explained 0.25; downgrade 3.75→2.75, second moat row dated 09-24, attribution 09-24 — no leakage). Supply 24→**25**. Factor 42,381→42,408. Policy **0 (correctly idle** — live matches canon 2,231 rows, 0 mismatches; forcing a revision would fabricate). | Dated-delta contract works (one lens votes on-ledger). Foresight at scale is **unproven** (1 quality row). No strategy may be benchmarked against the residual until multi-lens breadth exists (P2 gate). |
| T-4 | **Fiscal extraction + backfill complete, insert-stamping live** | Handover §3; findings §§11,12. Spec: body-after-first-newline only (header `FY:` is 100% noise), P1 Q-FY > P2 FY-range > P3/P4 > P5 > P6, confidences 1.0/0.9/0.7/0.5/0.3/0.2, backtest threshold ≥0.5. **1.4M scanned, 290,959 labeled (20.8%), live 292,246** with insert-stamping. Discovery-vs-fiscal lag 60–72% on 2026-08 discovery dates — `published_date` unusable as fiscal proxy. | Fiscal joins are the only bulk-release path that is PIT-safe today. Fiscal-only batches may flow; bulk annuals stay HELD (§1b D-1). |
| T-5 | **SIP backtest reconciled; benchmark post-tax XIRR 7.06%, signals trail 13–16bps** | Handover §§0,3. Artifact `sip_signal_legs_post_tax_2026-09-24.json`, 33 tests green, tax schedule source-cited. Objective frame: ₹1L on 2021-10-27 + ₹50k/mo SIP → ₹30.5L in; drawdown tolerance 40% (worst observed 11.65%). | This is the yardstick the 10cr book must beat **net of the same tax schedule**. Signals currently trail — no edge claimed. |
| T-6 | **Signal audit: residual structurally constant (all 3 red flags fire)** | Findings §1. `move_attribution` 136,642 rows; material 43,789, mean explained **0.110**, residual **0.890**; 22,423 material rows (51%) explained = 0; **0 rows** explained > 0.5. Directions on material: factor **42,346** / quality 0 / policy 0 / supply 0. Weights: factor 0.226 / quality 0.271 / policy 0.145 / supply **0.358** — 63% parked on mute lenses. `regime_tag='*'` everywhere. `share = w·1{pred==sign(realized)}` — a weight of agreement, not a fraction of the move. | Any strategy scored against this residual is **uninformative, not wrong**. Root cause per §2/H: levels without history (moat/ENI/ripple single-snapshot) cannot vote; returning 0 is correct. Fix = storage cadence/versioning, not predictor rewrites. |
| T-7 | **Drain + substrate state** | Handover §2; findings §§7,14. `embed-server` ready (Vulkan :8099, bge-small q8_0). Chunk index 1,398,908 rows dim 384 fresh. Quarantine 1,377. Screen degenerate (identical 0.3/0.25/0.25/0.2), dossiers SMA-identical + RSI 50.0. Writer FREE at handover. | Infra runs; measurement depth is hollow. T12 KEEP-small stands (infra verdict, not P&L edge). |

### 1b. REVOKED — must never regress (re-quote to block re-promotion)

| # | Revoked claim | Why it died (mechanics, not narrative) | Standing order |
|---|---|---|---|
| R-1 | **SELL +527bps, n=34, hit 1.00** (ex-T5) | Reproduces **only** with the book's artifact `exit_price` as fill (+553bps measured). On **market closes** over identical windows: **−20bps, hit 0.50**. `excess_table_v5/v6` is action-agnostic (no SELL cell); the number came from a removed ad-hoc script. Root: §2A — all 52 SELL rows long-framed (`target > entry`), `eod_scrip_calls` mechanically `×1.18/×0.94` on all 5,139 rows, `stop_hit = high ≥ stop` fires bar 1, `pnl = −1·(stop/entry−1) = +\|stop%\|` books a stop-out as a gain (46/46 `exit==stop`, pnl exactly `\|stop%\|`, days=1). | REVOKED 2026-09-23. Re-test only after terms-layer fix + closes-based excess + cohort-clustered stats. Never quote +527bps again except as artifact label. |
| R-2 | **Blended +29.8 book profit** (ex-T4/T5 gate premise) | Book P&L BUY −219.87 + SELL +249.67 = +29.8 is **entirely the SELL artifact** (§2A/§2B plan §1: "the +29.8 first profit is entirely the SELL artifact"). 43/44 closed BUYs exited at stop — the book measured *"does a name dip 6% before rising 18% in 60 sessions"* (bracket geometry), not any lens. | REVOKED. Never quote blended pnl as edge. Report BUY / SELL-avoidance legs separately, on closes, net of costs. |
| R-3 | **Confirmation (next-day stabilization) filter** (T10) | Live probe: stabilized 1W/29L; skipped-deep 0W/14L. Hit **0.03** — dead hypothesis, buried with numbers. | REJECTED, do not revisit without new evidence. |
| R-4 | **Trend-continuation entry** (T11) | Only 6/34 continuations; 28/34 sudden drops — continuation story dead as an entry filter. | REJECTED as entry filter. (Note: this is distinct from §2I's *forward* continuation regularity — see F2 for the honest reframe.) |
| R-5 | **Drain bulk release** (24,185 annuals pending) | Verdict **CONDITIONAL HOLD** (findings §14, unanimous): event-date/version columns absent on chunks/corporate docs (verified PRAGMA). Bulk HELD until those land; **fiscal-only batches may flow**. Order: annual_n200 → concall_n → annual_all → concall_all → refresh. | Do not bulk-release annuals in any backtest population join. Dated-delta features only from versioned/fiscal-stamped rows. |

---

## 2. T1–T12 honest audit (one line each + what each blocks)

| # | Strategy | Honest verdict | Evidence → implication for 10cr book |
|---|---|---|---|
| T1 | BUY unexplained weakness + intact quality + solvent (16-cell) | ❌ FAIL — 44 closed BUY, 1 win, mean −5.00; horizon excess Nifty −338bps / Midcap −299bps. | Baseline only. Failure is bracket geometry (§2B) + lone-residual betting (§2F), not proof reversal never works. Do not deploy. |
| T2 | Predictor honesty: levels GATE, flows VOTE | ✅ PASS (**method**, not edge) — dated Q/P/S shares → 0; explained 0.40–0.57 → 0.0, residual → 1.0. | Correct audit. Next: substrate versioning so true deltas can vote; no P&L until P2 gate flips at breadth. |
| T3 | Entry discipline: \|move\| ≥ 2σ floor | ✅ PASS (**gate**, not edge) — 17 sub-2σ BUY→HOLD demoted 09-18 (survivors NTPC 2.38×, TCS 2.21×). | Keep as entry precondition in all three families below. New-gate BUYs still open — forward closes required. |
| T4 | SELL widened broken-thesis | ❌ **ARTIFACT → REVOKED** (§1b R-1). Honest 20d read of same selection +790bps n=16 / 12 symbols / **5 weekly clusters** — interesting but ~6× underpowered. | Only honest SELL seed in the building. Rebuild as *avoided-loss* (cash-segment) with vol brackets + forensic veto = Family F1. |
| T5 | SELL realized-window excess | ❌ **NOT REPRODUCIBLE → REVOKED** (§1b R-1). | Rebuild excess table on closes with per-universe n + unmapped list = recipe §5. |
| T6 | BUY + factor (momentum) agreement | 🔄 INCONCLUSIVE — new BUYs 23 (vs 129 pre-gate); closed book still 44 old @ 1 win. | Forward closes needed. If new-gate BUYs still fail, selection needs forensic/accrual inputs before any timing tweak. F2 inherits this gate. |
| T7 | HOLD-everything-else baseline | ✅ PASS (**baseline**) — 646 HOLDs, hit 0.45–0.51. | Denominator honesty. HOLD win definition (5-session forward agreement) needs horizon-sensitivity check before use at 30/90/180/365. |
| T8 | Calibration folds → `apply_if_improved` | ✅ PASS (**gate behaves**) — `applied: false` every run (starved: one voting member, no per-lens edges to fit). | Re-run only after P0b (SELL regime represented + ≥2 lenses voting). Consider bandit/online alternative if batch folds keep refusing. Log every fold + apply-gate (goal success criterion). |
| T9 | Horizon exit = min(close, entry+h) | ✅ PASS (**method**) — 9 closed scored (was 0); v6 90 evaluated. All horizons identical while exits are stop-dates → horizon table is diagnostic, realized-window is the gate. | Keep `min(close, entry+h)` as the *scoring* convention; brackets determine realized exits. At 30/90/180/365 this distinction is the whole test. |
| T10 | Confirmation filter | ❌ FAIL (rejected, §1b R-3). | Dead. |
| T11 | Trend-continuation entry | ❌ FAIL (rejected, §1b R-4). | Dead as entry filter. |
| T12 | Embedding bge-small-384 vs bge-base-768 | ✅ VERDICT **KEEP small** — small 0.45/0.60 (substance 0.50/0.69) vs base 0.05/0.10; base 26% slower. Model gap, not construction (widened after TOC removal). | Infra lock-in (384-dim, no migration without DDL + 662k re-embed + fusion re-tune). Not a P&L leg. Revisit only with finance-tuned challenger + own concall Q/A. |

**Net: zero promotable P&L legs.** Five method/baseline passes (T2,T3,T7,T8,T9), one infra verdict (T12),
one inconclusive (T6), four dead/revoked P&L claims (T1,T4,T5,T10,T11 — T4's honest 20d read is the sole seed worth rebuilding).

### Why the failures share three mechanics (plan §2A–2M, structural facts only)

1. **Bracket geometry, not lenses (§2B + backlog 0b).** Fixed 18%/6% on all 5,139 call rows; 43/44 BUYs died at stop, median ~12 sessions. Any hold-time or lens study on this book measures the bracket. → All families below use **vol-scaled per-scrip brackets** (recipe §5.4).
2. **Mute lenses → constant residual (§§2F–2H).** `moat_evaluations` 1 row/ticker, policy 1 row/(ticker,policy), ripple 61 rows; dated branches return 0 by design; `residual>0.5` true on 100% of material rows; `solvency_ok` vacuous; `quality_intact` fails open. → No residual-scored selection until P2 breadth; families below select on **prices + financials + versioned deltas only** (PIT-safe).
3. **Benchmark + power illusion (§§2J–2M).** Index-relative carries ~0.4–1.0pp negative bias at 20s; matched XS control flips readings; 20-session tests had ≈2 independent cohorts (8 ISO weeks) — "hit 1.00" was illusory. Index breadth from 2025-09-01 gives 262 sessions ≈ 13 independent 20-session cohorts / ~52 weekly; at 30/90/180/365 the independent-cohort count is *smaller* per year, so the bar must be met by **spanning 2021-10→2026-09 (≈5yr price history, 1,265 dates) with weekly entry cohorts**, not by stretching one window. → Recipe §5 enforces XS control + cohort clustering + per-horizon cohort minimums.

Provisional readings (§§2I–2K) are explicitly **not** edge claims: short-horizon continuation (UP +0.23%/+0.55%/−0.07% at 1/5/20s; factor hit 0.533 at 1s, +0.45% gross → −0.05% net) is the only regularity, and it is **sub-cost** as measured. F2 is the honest attempt to see if it survives costs/controls at scale — with a pre-registered kill rule.

---

## 3. Three backtestable strategy families for the ₹10cr Oct-2021 book

Design constraints shared by all three (not repeated per family):
cash segment (no leverage, no short-notional P&L — SELL = **avoided-loss vs holding**, plan §5-Q4 recommended);
universe = 4 mapped benchmarks (**Nifty 50 / Midcap 150 / Smallcap 250 / Microcap 250**) with printed per-universe n + unmapped list (backlog #7);
horizons **30 / 90 / 180 / 365** sessions; entry cohorts = **ISO weeks** from Oct 2021; scoring per recipe §5.

### F1 — Forensic distress avoidance (econometrics + probability; drawdown-first)

**Hypothesis.** Names with deteriorating forensic quality (accruals, distress, capital discipline) underperform
and draw down harder over 90–365 sessions; in a cash book the monetizable edge is *not holding them*
(avoided loss + redeployment into clean carry), which also minimizes drawdown — the desk's co-objective.

**Math core.**
- Features (all PIT, pure SQL over existing financials — P2 queue, no new packages):
  Beneish M-score (8-variable probit weights), Altman Z'' for non-manufacturers + Z for manufacturers,
  Piotroski F (9 binary), Sloan accruals = (NI − CFO)/Assets, Δreceivables−Δsales, gross-margin deterioration.
- Cross-sectional standardisation per date × universe (z-scores; winsorise 1%/99% per date to bound microcap outliers).
- Selection econometrics: pooled **Fama-MacBeth cross-sectional logit** —
  `P(distress-loss | F)` per horizon; report odds ratios + cluster-robust t; no pooled OLS t-stat leakage across weeks.
- Scoring probability: avoided-loss excess per recipe §5.5; hit = avoided name underperforms its XS control over h.

**Rules (pre-registered).**
- Entry (SELL-as-avoid): at each weekly cohort, rank mapped names by composite distress
  `D = z(M) − z(Z) − z(F) + z(accruals)`; avoid (hold cash/gold sleeve instead) top-decile D within each universe,
  conditional on forensic inputs being PIT-available ≥30 sessions before cohort date (asof-validated; same discipline as fiscal §11).
- What it replaces: T4's broken-thesis OR-clause (Deteriorating OR moat<2.5 OR ENI<0) — same intuition, but
  continuous, PIT, audited inputs instead of single-snapshot levels. T4's honest +790bps/20d/n=16/5-clusters is the
  prior, not evidence.
- Exit/scoring: T9 `min(close, entry+h)` at 30/90/180/365; no bracket stop-out for the avoidance leg
  (cash held instead) — bracket geometry (§2B) must not contaminate a selection test.
- Sizing: equal-weight avoided names vs equal-weight XS control; book-level: avoided weight → 40% defensive sleeve
  (cash/gold/silver) when top-decile D coverage > threshold (pre-register 15% of mapped universe).

**Costs/taxes.** Same as recipe §5.7; avoidance leg turnover is low (quarterly financials cadence) so STCG bite is small —
  quantify, don't assume. Harvesting: book losses on exited distressed holds where realized.

**Falsification (kill rule).** Promote only on bar §5: ≥+500bps clustered net per horizon, ≥30 weekly cohorts
(use 2021-10→2026-09 weekly entries — ~250 cohorts available, so the bar is *attainable* here unlike P1's 3),
CI lower > 0.5, same sign both regimes, placebo ≈ 0. If 90/180/365 fail while 30 passes, promote **only** the passing
horizon — no horizon-averaging.

**Why it can pass where T4/T5 failed.** Inputs are time-varying financials (not single-snapshot moat/ENI);
fills are closes (not artifact exits); control is XS-matched (not biased index-relative); cohorts are ~50× P1's.

### F2 — Vol-scaled short-horizon dislocation momentum (statistics + probability; the §2I regularity, honestly costed)

**Hypothesis.** The ledger's only provisional regularity — short-horizon **continuation** (up-movers modestly
outperform down-movers at 1–5 sessions; factor hit 0.533 at 1s) — survives transaction costs only when entries are
restricted to genuine dislocations (≥2σ), factor-witnessed, vol-scaled, and scored against an XS control.
The action-table's reversal bet is the null; continuation is the alternative. Either outcome is publishable.

**Math core.**
- Noise floor per (symbol,date): trailing-20-session σ, clamped **[0.5%, 8.0%]** (P1 spec §6 rule, same as ledger floor).
- Dislocation: `|realized| / floor ≥ 2` (T3 gate, kept).
- Direction: factor = `sign(prev-day change)` — the only price-honest voter (plan §2N: needs only prices + static
  bootstrap weights, no substrate read, no look-ahead).
- Forward excess: close-to-close over h ∈ {30,90,180,365} **and** diagnostic 1/5/10/20 (to connect to §2I), XS-controlled
  (same-day mean of same population; index-relative secondary).
- Statistics: per-ISO-week cohort means → clustered SE (Liang–Zeger / Driscoll–Kraay analogue: cluster by week);
  hit-rate Wilson/binomial CI on **cohort-level** win fractions, not trade-level (plan §5 bar); placebo = shuffle-entry-date
  on same names (must ≈ 0).
- Stratify (pre-registered): noise-floor quintile × dislocation ≥2σ × realized sign × universe × regime.
  The pooled +0.2…+0.55pp quality-contrast lesson (§2L retraction: sign-flipping across quintiles) forbids pooled-only reporting —
  **quintile tables are mandatory**; if the edge lives only in q2/q5, say so and shrink it (no story-telling).

**Rules (pre-registered).**
- Long only: enter continuation (sign(prev) == sign(entry-day dislocation)) names at next close; skip reversal names.
- Bracket (must not repeat §2B): per-scrip vol-scaled — entry ± `k·σ_trailing20` with `k_target=3, k_stop=1`
  (≈3:1 risk unit mirroring P0's intent but scaled), clamped to [4%, 40%] target / [1.5%, 12%] stop; `k` fixed
  before the run, sensitivity ±1 in appendix only. SELL framing invariant from P0 enforced at write (never regress R-1).
- Sizing: volatility-targeted (position ∝ 1/σ, capped 5% of book per name, ≤40 names) — avoids microcap-vol dominance.
- Horizons: scored at 30/90/180/365 realized-window (T9); expected decay: edge (if any) concentrates at 30/90 and
  fades by 180/365 — pre-register this attenuation hypothesis so fading reads as confirmation, not failure.

**Costs/taxes (the binding constraint).** §2I measured +0.45% gross → −0.05% net of 50bps at 1s; 5s mean +0.91%
but median −0.17%. F2 therefore **must** report gross → net-of-measured-costs bridge per horizon and turnover-implied
holding-period return; high-turnover 30D sleeve pays STCG + STT on every round trip — include harvesting explicitly.
Kill rule: if 30D net clustered mean < +500bps or CI lower ≤ 0.5 after measured costs, **kill F2 fast** — do not
tune `k`/σ-window to rescue it (that path rebuilds §2B with extra steps).

### F3 — Regime-conditioned quality-carry + 40% defensive sleeve (econometrics + Kelly sizing; the 10cr compounding leg)

**Hypothesis.** Unconditional quality-carry is unproven (T1 −500bps; §2L retraction), but *regime-conditioned*
carry — full risk in calm breadth, capped risk + gold/cash buffer in fear — compounds over 180/365 sessions with
lower drawdown than buy-and-hold, because the 40% defensive sleeve earns its keep exactly when carry bleeds.

**Math core.**
- Regimes (2, pre-registered, price/breadth-only — no substrate read, no leak):
  RISK-ON vs RISK-OFF from `nse_index_breadth` (262 dates live; extend via prices to Oct 2021) —
  trailing-20-session index trend + breadth thrust/def breadth; VIX-quintile (P4) as secondary sort when VIX history lands.
  Regime label uses only data available at cohort date (asof). Report excess **same sign in both regimes** (bar) —
  magnitude may differ; sign may not.
- Selection: PIT quality-carry звание — Piotroski F ≥ 6 + Altman-safe + accruals-clean + promoter-holding-stable
  (P6 promoter-signaling PIT buys as overlay where in-DB PIT data exists; cheap, promote early per tracker).
  No moat/ENI levels as selectors (single-snapshot — §2H) until P0b versioning lands; moat may **gate** (moat<2.5 veto)
  exactly as T1's only live input, never rank.
- Sizing math: **fractional Kelly** (half-Kelly cap, 5% per-name cap) on the risky sleeve; defensive sleeve
  0–40% cash/gold/silver by regime posterior (RISK-OFF → 40%, RISK-ON → 0–10%); monthly rebalance (limits STCG churn).
- Exits: fixed-horizon holds (30/90/180/365) + OU half-life diagnostic (P4/P5) — OU only *diagnostic* until a leg
  passes the bar (tracker P5 BACKLOG rule).

**Rules (pre-registered).**
- Weekly cohorts buy clean-carry baskets (equal-risk-weight within universe, max 40 names, universe-neutral:
  allocate risk budget 25% per universe so microcap count cannot dominate notional).
- Defensive sleeve: Indian gold (SGB/ETF proxy closes in-DB where available, else cash) — instrument fixed before run;
  never switch proxy mid-run to flatter a regime.
- Drawdown accounting (co-objective): report max drawdown, Calmar, time-under-water, and sleeve-attributed
  drawdown reduction vs unconditional carry — minimal-drawdown is graded, not narrated.

**Costs/taxes.** 180/365 sleeves harvest LTCG treatment (>12m holds where applicable); 30/90 sleeves pay STCG;
apply the SIP-backtest's source-cited schedule (same schedule that produced the 7.06% benchmark) so the
10cr book is comparable to the ₹30.5L-in benchmark it must beat. STT 0.1% each side; 50bps impact prior replaced by
measured slippage audit (backlog #6) the moment it lands — re-state net, never silently keep the prior.

**Falsification.** If RISK-OFF carry still fails (wrong sign either regime) or the defensive sleeve's
drawdown reduction costs more carry than it saves (Calmar-negative vs cash), kill F3 and return the capital-frame
conclusion honestly: at 10cr, unconditional Indian quality-carry 2021–2026 did not clear costs — the SIP benchmark stands.

---

## 4. Honest backtest recipe (all three families; copy-paste into each run artifact)

**4.1 Population & point-in-time discipline.**
- Prices: `daily_price_delivery` from **2021-10-27** (1,265 dates live) — the 10cr inception. Index breadth from
  2025-09-01 live + price-derived breadth extension pre-registered (method fixed before results seen).
- Never join single-snapshot substrate (moat/policy/ripple levels, current ranker weights, today's peers) to past dates
  (plan §2M look-ahead machine). Allowed past joins: versioned history rows with `asof_date ≤ cohort date`
  (SBIN pattern), fiscal-labeled chunks (confidence ≥ 0.5, §11), PIT financials/forensics, PIT promoter buys.
- Quarantine: exclude `INE_AUTO_*` / quarantined masters on **every** inference read (backlog 0c; 4,770 attribution +
  7 call rows known-contaminated). `portfolio_actions` clean-only-incidentally is not a guarantee — predicate every query.
- Single SQLite writer + queue lock; never co-run GPU/DB jobs (handover §5).

**4.2 Materiality & entry gates (shared).**
- `realized` = close-to-close %; floor = trailing-20σ clamped [0.5, 8.0]; `is_material = |realized| > floor` (P1 spec §6).
- T3 gate: `|move| ≥ 2σ` mandatory for any dislocation entry (F2 strict; F1/F3 report sub-2σ sensitivity only).
- `solvency_ok` must be non-vacuous (rejects something — backlog 0/P0 gate); `quality_intact` fail-open closed.

**4.3 Yardstick (the §2J–2K fix).**
- Primary: **same-day cross-sectional control** (same-day mean of the *same* population/universe).
  Matched variant: same universe + moat-covered population for quality contrasts (the UP-broken +0.40 / UP-intact −0.15
  split pattern is the template).
- Secondary: index-relative (same-window universe-index close) for comparability to old tables — always paired, never alone.
- Every table prints **per-universe n + unmapped list** (backlog #7: 50 `is_nifty50=1`, 5,909 MICRO-default, 101 LARGE-unmapped today).

**4.4 Brackets & fills (the §2A–2B fix).**
- Fills: **market closes** (`min(close, entry+h)`, T9). Touch-fill only as labelled sensitivity with haircut (plan §5-Q3 default: close-through-the-level).
- Brackets: **vol-scaled per scrip** (F2 rule §3; F1 avoidance leg unscored by bracket; F3 fixed-horizon holds).
  Fixed 18%/6% is banned. SELL invariant (`target < entry < stop`) asserted at write (P0).
- SELL scoring: **avoided-loss vs holding** (cash-segment honest, plan §5-Q4 recommended) — never short-notional P&L.

**4.5 Horizons × universes × cohorts (the power fix).**
- Grid: **30 / 90 / 180 / 365 sessions × Nifty50 / Midcap150 / Smallcap250 / Microcap250** (4×4 = 16 cells per family).
- Entry cohorts: **ISO weeks** Oct-2021 → Sep-2026 (~250 weekly cohorts available — the bar's ≥30 is attainable;
  P1's 3-cohort reads were the underpowered regime this replaces).
- Statistics per cell: cohort-mean excess (net), median, **cluster-robust SE + CI** (cluster = ISO week),
  cohort-level hit rate + Wilson CI (never trade-level n as power), # cohorts, # names, # symbols.
- Regimes: same 2-regime split for all families; **same-sign-both-regimes** required; report per-regime cells.
- Calibration folds (T8): log every fold + `apply_if_improved` fire/no-fire (goal criterion); bandit alternative only if
  batch folds keep refusing *after* ≥2 lenses vote.

**4.6 Placebo & sensitivities (falsification is graded).**
- Mandatory: **shuffle-entry-date placebo** on same names (same horizons/universes) → must ≈ 0 (bar).
- Sensitivities (appendix, never headlined): index-relative vs XS; touch- vs close-fill; `k±1` bracket; Q-FY vs FY-range
  fiscal threshold; VIX-included vs breadth-only regimes. A family that passes only one sensitivity setting fails.

**4.7 Costs, taxes, harvesting (net means net).**
- Bridge per cell: gross → net-of-**measured** costs. Start from 50bps round-trip impact prior + STT 0.1%/side;
  replace impact with slippage-audit measurement (backlog #6) when it lands and re-state.
- STCG/LTCG per source-cited schedule shared with the SIP backtest (the 7.06% benchmark's schedule):
  holding-period-aware per sleeve (30/90 → STCG-heavy; 180/365 → LTCG-harvested); harvesting booked explicitly;
  gold-sleeve tax treatment stated separately, never blended silently.
- Report turnover, churn-implied cost drag, and cost-per-unit-excess per cell. `summarize()`-style blended win rates
  (positional pnl-wins + 0.5 HOLD agreement → 0.51) are **never quoted as hit rates** (plan §4).

**4.8 Reporting & scope stamping (goal success mapping).**
- Each run artifact stamps: book size at run, EOD max date, universe n + unmapped list, cohort counts per cell,
  cost schedule version, regime definition version, quarantine predicate hash, placebo table.
- Goal checklist per artifact: ~~0 pending ingest~~ (drain-gated, not quant's call) / ≥30 closed BUY/SELL with forward OHLC
  (flow-dependent) / **4×4 excess table 30/90/180/365 × 4 universes** (this recipe's deliverable) / calibration folds + apply-gate logged.
- Scope caveats on every artifact (P1 precedent): what population is missing (small/micro call coverage → P7 hierarchical
  shrinkage stays BLOCKED until it lands; victim is F2/F3 micro cells — say so).

---

## 5. Regression guard (what this plan refuses to do)

1. Never re-quote R-1–R-4 as live edge (table §1b is the blocklist).
2. Never score against the constant residual until the P2 multi-lens gate flips (quality+supply breadth at scale, not one SBIN row).
3. Never backfill call rows for 2025-09→2026-06 with today's substrate (§2M) — historical extension uses price-only terms (plan §2N: 755,494 rows / 5,223 symbols / 274 dates / 207,152 material from prices alone is the safe evidence expansion).
4. Never tune brackets/fills/controls to rescue a failing family (that's §2B rebuilt with extra steps).
5. Never blend sleeves, horizons, or regimes into one headline number — 16 cells + 2 regimes + placebo, or it didn't happen.

## 6. Sequencing (DB-writer-safe; cheapest signal first)

1. **F1 forensic screen** — pure SQL over existing financials (P2), no GPU, no drain contention. Validates the drawdown co-objective first.
2. **F2 continuation-momentum grid** — price-only (§2N recipe), read-only, runnable during drains; pre-registered kill rule bounds compute.
3. **F3 regime-carry + defensive sleeve** — needs breadth/VIX history assembly; runs last; monthly-rebalance turnover keeps writer load trivial.
4. P3/P4/P5 (GARCH floors, VIX conditioning, OU/Kelly/EVT, BSTS/BMA/bandits/conformals) only **after** a family clears the bar — tracker order stands.

*Acceptance: this file exists with TRUE-vs-REVOKED (§1) + 3 specs (§3) + recipe (§4). No formatter/linter/suite run per assignment.*
