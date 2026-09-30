# Desk: Macro / Behavioral / Quant-Fin Edge — 2026-09-25

> Status: PROPOSAL, pre-bar. No weights, predictors, schema, or DB rows changed by this doc.
> Parents: `tasks/strategy_tracker.md` (T1–T12, P1–P7 queue, promotion bar §5, backlog 0–8) ·
> `tasks/next_wave_plan_2026-09-23.md` (§§2–5, esp. §4 P3/P4 + §5 promotion bar + §5 open decisions) ·
> `tasks/test_findings_2026-09-24.md` (§§1–14, esp. §§2–3 mute-lens root cause, §8 backlog, §14 drain verdict) ·
> `tasks/SESSION_HANDOVER_2026-09-25.md` (guardrails, REVOKED list, capital frame).
> Promotion bar (restated, per-horizon): cohort-clustered mean excess ≥ **+500bps net of measured costs**,
> **≥30 weekly cohorts** (≥13 for 20-session holds) spanning **≥2 index regimes**, hit-rate CI **lower bound > 0.5**
> (cluster-robust), **same sign in both regimes**, **shuffle-entry-date placebo ≈ 0**.
> Capital frame: ₹10cr cash Oct 2021; may hold cash/gold/silver up to 40% when not ROI-positive.
> Costs: 50bps impact + STCG/LTCG + STT + harvesting + slippage (measured, not assumed, at gate time).
> REVOKED (never regress): SELL +527bps artifact, blended +29.8 profit, confirmation filter (T10), trend entry (T11).

## 0. Gating preamble — why everything below is TEST-ONLY-PAST-BAR

- Test-findings §§2–3 (dated evidence): quality/policy/supply predictors return neutral because inputs are
  **levels without history** (moat score, ENI snapshot, ripple edge, no time axis). A constant cannot explain
  a move; returning 0 is correct. Fix = storage cadence/versioning (P0b: moat/ENI/ripple history + dated deltas),
  **not** predictor rewrites. Ledger consequence: residual structurally ≈0.89, weights parked on mute lenses
  (supply 0.358 + quality 0.271 = 63%), regime_tag `'*'` everywhere. Scoring any strategy below against the
  current residual is uninformative, not wrong.
- Contract preserved (T2): **levels GATE, flows VOTE**. Deltas vote (downgrade/drop = −1, upgrade = +1);
  levels keep gating; `asof_date=None` keeps legacy behavior (`eod_corrector.py:34-51`).
- Order of operations (next_wave §4): honest book (SELL framing invariant `target < entry < stop`, P0) +
  honest yardstick (same-day cross-sectional control, universe map fix) + honest time (as-of/PIT reads) +
  honest evidence base (≥13 × 20D cohorts / ~52 weekly) + P0b versioning (≥2 lens families voting, residual
  gains variance, folds have edges to fit) **must land before** P3 conditioning or P4 sizing/exit is tested.
- P3 (tracker queue): GARCH floors + VIX-regime conditioning + investor-majority — excess by VIX quintile.
  P4: OU half-life exits, fractional Kelly, EVT stops — **only for a leg past the bar** (bar met in both
  regimes, placebo ≈ 0). P5 (Kelly/OU/EVT/BSTS/BMA/bandits/conformals): BACKLOG until book stabilizes.
- Drain interaction: 24,185 annuals pending stay HELD until event-date/version columns land (conditional hold,
  §14); fiscal-only batches may flow. Nothing below needs bulk annuals — all specs are price/market-data-first
  with PIT discipline, so they neither unblock nor delay the drain.

## M1. VIX-regime conditioning (P3)

**Question:** does the (future, post-bar) leg's excess concentrate in high-fear regimes, and does it keep its
sign in calm regimes (bar requirement)?

1. **Source.** India VIX daily close (NSE). Primary: `nse_index_breadth`-adjacent market-data store if VIX
   column exists; else NSE archival VIX CSV ingested read-only with as-of date = trading date. Fallback if
   neither lands: Nifty trailing-20σ percentile as fear proxy — labelled PROXY, never called "VIX".
2. **Regime definition (pre-registered, no peeking).** Trailing-252-session rolling quintiles of VIX level,
   computed strictly as-of date *t* (no forward window). Report Q1 (calm)…Q5 (fear); collapse to
   calm (Q1–Q2) / mid (Q3) / fear (Q4–Q5) terciles for the small-n fear cell. Alternative cut (fixed
   thresholds, e.g. VIX <15 / 15–25 / >25) as labelled sensitivity only.
3. **Measurement.** For the gated leg only: forward excess (1/5/10/20 horizons; 20D needs ≥13 cohorts) split by
   regime at entry date, under the same-day cross-sectional control primary + index-relative secondary
   (next_wave §6.5). Per-regime: cohort count, mean/median excess, cluster-robust hit-rate CI, universe split.
4. **PIT discipline.** Regime label uses VIX close at/before entry date only. Historical extension uses
   price-only terms (next_wave §M) — today's VIX curve never stamped onto the past.
5. **Costs.** Net of measured costs (50bps impact prior + STCG/LTCG + STT + slippage audit); fear-regime
   slippage haircut printed separately (spreads widen when VIX spikes — tracker backlog 6 mechanism lens).
6. **Kill criteria (falsification).** Fear-cell excess < +500bps net; OR sign flips between calm and fear
   (bar: same sign both regimes); OR fear cell has < minimum-n (pre-register: ≥30 weekly cohorts pooled,
   ≥10 per tercile for a directional claim); OR per-regime placebo ≠ ≈0. Any one kills the conditioning claim;
   the underlying leg keeps whatever verdict it had without conditioning.
7. **Small-n warning.** Top-fear quintile is rare by construction (~20% of dates, fewer independent 20D
   cohorts). No claim on <13 independent 20D cohorts; report the cohort count next to every fear-cell number.

## M2. GARCH(1,1) per-scrip floors (P3; fixes backlog 0b)

**Question:** replace the fixed 18%/6% bracket (43/44 closed BUYs exited at stop — bracket geometry, not a lens
verdict) with per-scrip volatility-scaled terms, and re-test whether any lens verdict survives.

1. **Spec.** Per symbol, GARCH(1,1) on daily close-to-close log returns, estimated on trailing-252 sessions
   as-of entry date (minimum 126 observations; else fallback). Conditional vol σ_cond(t) → entry floor and
   bracket: materiality floor = max(2σ_cond, clamp[0.5%, 8.0%]) — consistent with the ledger's trailing-20σ
   clamp rule (next_wave §6.2); target = entry × (1 + k_t·σ_cond), stop = entry × (1 − k_s·σ_cond) with
   pre-registered k_t = 3, k_s = 1 (mirrors the old 3:1 risk unit; SELL mirrored `target < entry < stop`).
   Clamp bracket half-widths to [2%, 25%] to avoid penny-vol explosions and illiquid-name nonsense.
2. **Estimation universe.** Nifty-50 first (price history deepest, 1,265 dates 2021-10-27→; breadth bound
   2025-09-01 → ~13 independent 20D cohorts). Expand to midcap only after N50 gate passes. Small/micro need
   slippage measurement first (backlog 2) — blocked, not queued.
3. **Fallback.** If GARCH fails to converge for a symbol-date: trailing-20σ (same clamp) labelled FALLBACK;
   print fallback rate. If fallback rate > 10% of entries, the floor comparison is VOID (estimation broken,
   not a strategy result).
4. **PIT discipline.** σ_cond uses returns strictly ≤ entry date. Re-estimation cadence: monthly (or on
   bracket open); no in-flight refit using the holding window.
5. **Comparison (falsification).** Head-to-head on the same entries: GARCH-bracket realized-window P&L vs
   fixed-18/6-bracket P&L vs close-through-the-level fill sensitivity (open decision §5.3 — default
   close-through, touch-fill as labelled sensitivity). GARCH floors PASS iff they (a) cut stop-exit dominance
   materially (pre-register: stop-exit share < 70% vs 43/44 baseline) AND (b) the gated leg's clustered excess
   improves vs fixed bracket without breaking bar criterion 1 (≥+500bps net). If (a) without (b): engineering
   win, no strategy promotion. If neither: keep fallback trailing-σ, drop GARCH (complexity unjustified).
6. **Open-decision tie-in.** Bracket rule choice (§5.2: GARCH vs trailing-σ percentile + clamp) is settled by
   this test's head-to-head, not by argument. Clamp values above are the proposal; the test may revise them
   once, pre-registered before the rerun.

## M3. FII/DII vs promoter conditioning (P3 + P6-cheap)

**Question:** does dislocation direction interact with who dominates the register — foreign institutions vs
promoters — given the ledger's base rates (investor_majority: promoter 61% · all 29% · retail 8% · FII 1.8%)?

1. **Base-rate honesty.** FII-majority rows are ~1.8% of material rows — any FII-conditioning cell starts
   starved. Pre-register minimum-n: no FII-directional claim on < 30 pooled weekly cohorts; report per-cell n
   always. Promoter-majority cells are the only ones with plausible power today.
2. **Conditioning spec.** For the gated leg: split entries by investor_majority (promoter / FII / DII-or-all /
   retail) × dislocation sign (DOWN-dislocated vs UP-dislocated, ≥2σ floor per T3). Primary contrast:
   FII-heavy + DOWN-dislocated vs promoter-heavy + DOWN-dislocated (forced-selling vs insider-conviction
   narrative, tested as interaction, not assumed). DII data: use only if a dated DII-flow series lands;
   otherwise DII stays inside "all", labelled.
3. **Promoter-signal join (P6 cheap, PIT).** In-DB promoter buy disclosures (PIT buys) join as-of entry date:
   entry within +60 sessions after a disclosed promoter buy = "promoter-bid" flag. No future disclosures leak
   into past entries. If PIT table lacks as-of coverage, this sub-test is BLOCKED (not failed) — say so.
4. **FII-flow overlay (if series lands).** Net FII cash/flow quintile as-of entry × dislocation sign; same
   quintile-as-of discipline as M1. Without a dated FII series: overlay stays PROPOSED, conditioning runs on
   register-majority only.
5. **Costs/sizing.** Equal-weight at this stage (sizing is P4-gated). Print turnover per cell — FII-heavy names
   churn more; net-of-costs decides.
6. **Kill criteria.** Interaction spread (FII-DOWN minus promoter-DOWN) < +300bps net with overlapping
   cluster-robust CIs; OR sign flips across the two index regimes; OR any cell's placebo ≠ ≈0; OR promoter-bid
   flag adds nothing over register-majority alone (then drop the join — weightless code deleted per taste).
   Surviving contrast must still clear the full bar before it touches sizing.

## M4. Kelly sizing + OU exits + EVT stops (P4 — STRICTLY GATED)

> All three activate ONLY for a leg that has cleared the full promotion bar (both regimes, placebo ≈ 0).
> Testing any of them on a failing leg is out of scope — sizing a negative edge maximizes ruin, not return.

### M4a. Fractional Kelly sizing

1. **Edge inputs.** Per-leg win probability p and payoff ratio b estimated from cohort-clustered,
   net-of-measured-costs history only (≥30 weekly / ≥13 20D cohorts). Shrink p toward 0.5 with a
   Beta-prior (pseudo-count = 10 cohorts) — small-sample Kelly is a ruin machine without shrinkage.
2. **Fraction.** Half-Kelly (¼-Kelly sensitivity), capped: ≤5% of book per name, ≤25% net exposure per leg,
   gross ≤100% (cash segment, no leverage). When no leg clears the bar: hold cash/gold/silver up to the 40%
   buffer — sizing rule outputs "no bet", never forces capital into a failing leg.
3. **Costs/taxes.** Kelly fraction computed on NET edge (50bps impact + STT + slippage-audit value +
   STCG/LTCG schedule by holding period, with harvesting). Recompute net edge per horizon — short holds pay
   STCG; the fraction must earn it.
4. **Kill criteria.** Out-of-sample (walk-forward, PIT) log-growth ≤ equal-weight log-growth; OR max drawdown
   exceeds the 40% tolerance mapping (worst observed 11.65% — size must keep simulated worst-drawdown < 25%
   with margin); OR turnover doubles for < +100bps gain (friction eats the fraction → drop to ¼ or equal-weight).

### M4b. OU (Ornstein–Uhlenbeck) half-life exits

1. **Spec.** On the gated leg's residual/excess series (post-bar, index-relative or XS-controlled): fit
   OU dx = θ(μ − x)dt + σdW per name (pooled-θ sensitivity); half-life t½ = ln2/θ. Exit rule: time-stop at
   max(1×t½, horizon cap) OR convergence (residual decays to < 0.25σ) OR bar-stop, whichever first.
   Pre-register θ estimation window (trailing-126 sessions, entry-as-of).
2. **Comparison.** OU exits vs fixed-horizon exits (1/5/10/20) on identical entries, realized-window scoring
   (T9: min(close, entry+h) is diagnostic; realized window gates). OU wins iff clustered net excess ≥ fixed
   best +100bps with same-sign regimes and placebo ≈ 0.
3. **Kill criteria.** Median t½ < 2 sessions (noise, not mean-reversion — exits degenerate to scalps friction
   kills); OR t½ > 60 sessions (no reversion inside the evidence window — OU is story-telling); OR θ
   unstable across halves (sign/2× magnitude shift → process not OU, drop the model, keep fixed exits).

### M4c. EVT (extreme-value-theory) tail stops

1. **Spec.** Per-name left-tail stop from trailing-252-session losses: fit GPD over threshold (95th-percentile
   loss); stop = max(GARCH stop from M2, EVT 99% conditional-loss level), clamped to the M2 [2%, 25%] band.
   EVT only ever WIDENS-vs-GARCH within the clamp — it is a tail guard, not a profit stop.
2. **Comparison.** EVT-augmented stops vs M2 GARCH stops alone: fewer >3σ overnight gaps AND no worse
   clustered net excess (tolerance −50bps — insurance costs something; more than that, drop it).
3. **Kill criteria.** Gap-event count unchanged over ≥30 cohorts (no insurance paid out — dead weight); OR
   stop-widening converts winners into gap-losses (excess drops > 50bps); OR < 5 tail events in-sample
   (nothing to fit — EVT is decoration, delete it).

## B1. Behavioral edge — guidance-change drift (dated-delta discipline)

**Thesis (anchoring + underreaction):** the market underreacts to concall guidance revisions because analysts
anchor on the prior guide; the drift accrues over 5–20 sessions as numbers get revised. This is the panel's
top extraction upgrade (§14: guidance-change diff — raised/lowered/maintained + magnitude) feeding the only
mechanism proven on-ledger (dated deltas, SBIN −1).

1. **Signal.** Concall guidance-change diff per (symbol, date): raised / maintained / lowered × magnitude
   (bps of revenue/EBITDA guide change; magnitude tercile). Entry: lowered-guide + DOWN-dislocated (≥2σ,
   intact-forensics gate per P2 veto) → BUY-the-overreaction-to-bad-news; raised-guide + UP-dislocated →
   no-chase (HOLD) — direction pre-registered, not fitted both ways.
2. **Why this is NOT the revoked confirmation filter (T10).** T10 waited a day for price stabilization and
   died 1W/29L — it filtered on price action after the fact. B1 filters on the dated INFORMATION event
   (guidance text diff as-of the concall date) and enters on dislocation, never on stabilization. Any
   "wait-a-day" variant is explicitly out of scope; proposing it re-opens a buried hypothesis without new
   evidence and trips the REVOKED tripwire (§F).
3. **Why this is NOT trend entry (T11).** T11 bet continuation on prev<0 & day<0 price paths; sudden drops
   dominated and the story died. B1 bets on information-drift after a guidance event, conditioned on the
   forensic veto + quality gate — price path is not the signal.
4. **PIT/versioning needs.** Requires the guidance-change diff writer appending genuinely new dated rows
   (P0b pattern: two DATES per key for deltas); same-day upserts collapse by day-key by design. Until the
   writer exists, B1 is PROPOSED with zero backtest — no historical guidance labels may be hand-filled (that
   fabricates foresight; policy-lesson §10).
5. **Test (post-P0b).** Cohort-clustered excess 5/10/20D × raised/lowered × magnitude tercile, XS control,
   per-universe n + unmapped list (backlog 7), placebo on shuffled concall dates. Promotion needs the full bar.
6. **Kill criteria.** Lowered-guide drift ≤ 0 at 20D over ≥30 cohorts; OR drift exists only in maintained
   (no-information) cell — then it's noise, not underreaction; OR magnitude terciles unordered (no dose
   response — story without a gradient dies); OR forensic-vetoed names drive the whole effect (then P2 veto
   is the edge, not guidance — reattribute, don't co-claim).

## B2. Behavioral edge — fear-displacement entry (VIX-high + intact-quality, forensic-first)

**Thesis (availability + capitulation):** index-fear episodes trigger indiscriminate selling; intact-quality
names (forensic veto passed, moat gate passed) bounce hardest as fear mean-reverts. Entry buys displacement,
not weakness — quality-first distinguishes it from the failed lone-residual BUY (T1, −500bps).

1. **Signal.** Entry ALL THREE must hold as-of date *t*: (a) fear regime (M1: VIX Q4–Q5 or proxy ≥70th
   percentile); (b) DOWN-dislocated ≥2σ (T3 floor); (c) intact quality AND forensic veto passed
   (Beneish/Altman/Piotroski per P2 — no pass, no entry). Missing any one → HOLD. This is a triple-gate, so
   the eligible set is small by design — report eligibility rate.
2. **Why this is NOT confirmation (T10) or trend (T11).** No stabilization wait (anti-T10: enter INTO fear,
   not after calm); no continuation bet (anti-T11: entry is counter-trend by construction, conditioned on
   quality rather than price path). Either mutation (wait-for-calm, buy-the-bounce-path) is out of scope.
3. **Exit/sizing.** Fixed-horizon scoring until M4 gates open; if a B2 leg clears the bar, OU exits (M4b)
   and fractional Kelly (M4a) apply in that order. No sizing on unproven B2 — equal-weight test only.
4. **Test (post-bar-gate).** Fear-entry excess vs calm-dislocated excess (same gates minus fear) vs
   fear-without-quality (broken names in fear — must NOT work; if it does, the edge is beta, not quality,
   and the thesis is reattributed). Regimes ×2, placebo on shuffled fear labels.
5. **Kill criteria.** Fear+intact ≤ calm+intact (no fear premium); OR fear+broken ≥ fear+intact (quality adds
   nothing — thesis dead, do not rebrand as "fear factor"); OR eligible n < minimum (then B2 is a valid but
   untestable idea — park it, don't dilute the bar); OR sign flips across the two index regimes.

## F. Falsification matrix (kill-table)

| # | Claim | Kills it (any one) |
|---|---|---|
| M1 | Fear concentrates excess | fear-cell net < +500bps · sign flips calm↔fear · tercile n < 10 · per-regime placebo ≠ ≈0 |
| M2 | GARCH floors beat fixed 18/6 | stop-exit share stays ≥70% · no clustered-excess gain vs fixed · fallback rate >10% (void) |
| M3 | FII/promoter interaction | spread < +300bps net w/ overlapping CIs · regime sign flip · placebo ≠ ≈0 · promoter-bid adds nothing (drop join) |
| M4a | Fractional Kelly sizes the book | OOS log-growth ≤ equal-weight · simulated worst-DD ≥25% · turnover doubles for <+100bps |
| M4b | OU half-life exits | t½ <2 or >60 sessions · θ unstable across halves · no +100bps over fixed best |
| M4c | EVT tail stops | gap count unchanged ≥30 cohorts · excess drops >50bps · <5 tail events in-sample |
| B1 | Guidance-change drift | 20D drift ≤0 (≥30 cohorts) · effect only in maintained cell · no magnitude gradient · vetoed names drive it |
| B2 | Fear-displacement entry | fear+intact ≤ calm+intact · fear+broken ≥ fear+intact · eligible n < minimum · regime sign flip |
| GLOBAL | REVOKED-regression tripwire | any spec reintroduces next-day-stabilization filter, prev<0&day<0 continuation entry, book-`exit_price`-as-fill scoring, or blended positional+agreement "win_rate" — that spec section is void on sight |

## G. Non-goals + guardrails

- No weight changes (BOOTSTRAP weights frozen until calibration earns `applied:true` post-bar).
- No predictor rewrites (flows-VOTE contract stands; versioning is a P0b writer task, not this doc).
- No schema/DB edits (denylist: `reality_engine/db/repository.py`, `schema.sql`; no live-row deletes;
  no `git stash`; no new packages; single SQLite writer + queue lock; never co-run GPU/DB jobs — this doc
  touches only this markdown file).
- No retest of REVOKED artifacts (SELL +527, blended +29.8, T10, T11) — cited only as tripwires.
- No strategy benchmarked against the residual until the P0b gate flips (quality/policy/supply dirs > 0
  on-ledger at breadth — currently quality 1 row, supply 25, policy correctly idle).
