# Strategy Tracker — tested / results / pending / improvements (living doc)

> Last updated: 2026-09-23 (T12 embed verdict KEEP small; SELL promotion REVOKED — see T4/T5 + next_wave_plan_2026-09-23.md §2A; promotion bar §5)
> Rule: update this file after every strategy test (result + evidence + next). Promotion bar (revised 2026-09-23, full form in `tasks/next_wave_plan_2026-09-23.md` §5): cohort-clustered mean excess ≥ +500bps net of **measured** cost, ≥ 30 weekly cohorts across ≥ 2 index regimes, hit-rate CI lower bound > 0.5, same sign in both regimes, plus a shuffle-entry-date placebo ≈ 0. The old single-line bar ("walk-forward folds + `apply_if_improved` + net ≥ +500bps net of 50bps") was satisfied by a framing artifact — see the revocation below.

## Tested strategies (with live results)

| # | Strategy | Hypothesis | Test (command / artifact) | Result | Status | What improves it next |
|---|---|---|---|---|---|---|
| T1 | BUY unexplained weakness + intact quality + solvent (original 16-cell) | Panic-alpha bargain: weakness the substrate can't explain = mispricing | `seed_track_record.py` over 60d attribution; `excess_table_v3` | 44 closed BUY, 1 win, mean pnl −5.00; horizon excess Nifty −338bps / Midcap −299bps | ❌ FAIL | Killed by T4+T5 gates below; kept as baseline only |
| T2 | Predictor honesty: levels GATE, flows VOTE | A constant level (moat/ENI/significance) cannot explain a directional move | `test_eod_corrector` + `test_move_attribution` (58 green); re-attribute probe | Dated Q/P/S shares → 0; explained 0.40–0.57 → 0.0, residual → 1.0 | ✅ PASS (method) | Needs substrate versioning (moat/ENI/ripple history columns) so true deltas can vote |
| T3 | Entry discipline: BUY needs \|move\| ≥ 2σ floor | 1.43×-floor entries buy noise, not dislocation | `test_action_thesis` 25 green; RELIANCE 1.31× demoted to HOLD | 17 sub-2σ demoted BUY→HOLD on 09-18 probe; survivors NTPC 2.38×, TCS 2.21× | ✅ PASS (gate) | New-gate BUYs still open — forward sessions must close them before excess reads |
| T4 | SELL widened broken-thesis: Deteriorating OR moat<2.5 OR ENI<0 | Unexplained strength in broken-quality names mean-reverts | `seed v5`: 52 SELL seeded; re-audit 2026-09-23 (`portfolio_actions`, `portfolio_ledger.mark_to_market`) | **❌ ARTIFACT.** 46 closed, "46/46 wins" — but all 52 SELL rows carry `target > entry` (long-framed terms; `eod_scrip_calls` is `×1.18/×0.94` for all 5,139 rows). `stop_hit = high >= stop` then fires on bar 1 and `pnl = −1×(stop/entry−1) = +|stop%|`: **46/46 exited at `exit_price == stop_loss`**, pnl exactly `|stop%|` (6.48, 7.42, 5.32…), days=1 | ❌ REVOKED | Fix framing at the terms layer (SELL ⇒ target<entry<stop), then re-seed and re-test. Honest 20d read of the same selection: +790bps, n=16, 12 symbols, **5 weekly clusters**, all inside the 08-20→09-18 index-down window — suggestive, not proven |
| T5 | SELL realized-window excess vs universe index | Short-notional window return − index same-window − 50bps | Re-derived 2026-09-23 from `portfolio_actions` + `nse_index_breadth` closes | **❌ NOT REPRODUCIBLE on market closes.** `+527bps n=34 hit 1.00` reproduces **only** with the book's artifact `exit_price` as the fill (measured +553bps, hit 1.00). With market closes over the same windows: **−20bps, hit 0.50**. `excess_table_v5/v6` is action-agnostic (no SELL cell) — the promoted number came from the removed ad-hoc script | ❌ REVOKED (gate not met) | Rebuild the excess table on closes with cohort-clustered stats and printed per-universe n + unmapped list |
| T6 | BUY with factor (momentum) agreement | Reversal needs at least one flow witness; lone residual is not a thesis | `test_action_thesis` dislocation+factor tests; seed v5 | New BUYs 23 (vs 129 pre-gate); closed book still 44 old @ 1 win | 🔄 INCONCLUSIVE (new book open) | Forward closes needed; if new-gate BUYs still fail, selection needs Beneish/accrual inputs |
| T7 | HOLD-everything-else baseline | Denominator honesty for hit-rates | `summarize()` | 646 HOLDs, hit 0.45–0.51 | ✅ PASS (baseline) | HOLD win definition (5-session forward agreement) needs horizon-sensitivity check |
| T8 | Calibration folds → `apply_if_improved` | Weights move only on out-of-sample improvement | `run-calibration` (multiple runs) | Folds decided, `applied: false` every run ("no out-of-sample improvement") | ✅ PASS (gate behaves) | Re-run on v5+ book with SELL regime represented; consider bandit (online) alternative |
| T9 | Horizon exit = min(close, entry+horizon) | Stopped-out positions score realized window, not hypothetical hold | `test_horizon_excess` 21 green; table v2→v3 | 9 closed scored (was 0 evaluable); v6 90 evaluated | ✅ PASS (method) | All horizons identical while exits are stop-dates — horizon table is diagnostic, realized-window is the gate |
| T10 | Confirmation (next-day stabilization filter) | Waiting a day filters losers | Live probe: stabilized 1W/29L; skipped-deep 0W/14L | Hit 0.03 — dead hypothesis, buried with numbers | ❌ FAIL (rejected) | Do not revisit without new evidence |
| T11 | Trend-continuation entry (prev<0 & day<0) | Only 6/34 were continuations; 28/34 sudden drops — continuation story dead | Live probe | Sudden-drop dominates; not an entry filter | ❌ FAIL (rejected) | — |
| T12 | Embedding model: bge-small-384 (incumbent) vs bge-base-768 (challenger) | Bigger model retrieves finance passages better | Prototype on 2 annual reports (SAIL 6490 + 6491), 20 Q/A from chunk text, recall@1/@5 same cosine path; substance split 16 kept / 4 TOC dropped with rule persisted | Full: small 0.45/0.60 vs base 0.05/0.10. Substance: small **0.50/0.69** vs base **0.00/0.00**. Gap widened after TOC removal — model, not construction. Base also 26% slower/embed (43.9 vs 34.8ms) | ✅ VERDICT: KEEP small, no migration | Revisit only with a finance-tuned challenger + own concall Q/A set; migration needs DDL + 662k re-embed + fusion re-tune (384-dim lock-in) |

## Pending queue (from `tasks/modeling_bucket_list.md`, in test order)

| # | Idea | Family | Needs | Status |
|---|---|---|---|---|
| P1 | Momentum-vs-reversal by horizon (30/90/180/365) | stats/econ | Book + ledger (in hand) | NEXT — start when drain frees DB writer |
| P2 | Beneish M / Altman Z / Piotroski F + accrual quality | forensic | Pure SQL over existing financials | QUEUED (feeds 46/46 SELL leg) |
| P3 | GARCH floors + Loughran-McDonald sentiment | stats/sentiment | Price history + 662k chunks (in hand) | QUEUED |
| P4 | VIX-regime conditioning (best cells at highest fear?) | sentiment | Breadth VIX data (partial) | QUEUED |
| P5 | Kelly sizing, OU exits, EVT stops, BSTS counterfactuals, BMA, bandits, conformals | math/bayes/ML | Book must stabilize first | BACKLOG |
| P6 | Promoter signaling event study (in-DB PIT buys) | game theory | PIT data (in-DB) | BACKLOG (cheap — promote early) |
| P7 | Hierarchical sector→stock shrinkage (small/micro cells) | bayes | Small/micro call rows (missing) | BLOCKED on coverage |

## Improvement backlog (subsequent tests)

0. **BLOCKER — level framing.** SELL rows carry long-framed terms; `mark_to_market`'s mirrored trigger books a stop-out as a gain. Fix at the terms layer (SELL ⇒ `target < entry < stop`, mirroring the long's risk unit) + a `record_action` invariant + regression test. Then re-seed and re-run T4/T5. Full plan: `tasks/next_wave_plan_2026-09-23.md` §4 P0.
0b. **BLOCKER — fixed 18%/6% bracket.** All 5,139 call rows use the same bracket regardless of vol; **43/44** closed BUYs exited at `stop_loss` (median ~12 sessions), so BUY 1/44 is bracket geometry, not a lens verdict. Vol-scale per scrip (GARCH(1,1) or trailing-σ, clamped) before any horizon/lens study.
0c. **BLOCKER — quarantine join.** `seed_track_record` has none; `move_attribution` carries **4,770** rows and `eod_scrip_calls` **7** rows on quarantined synthetic `INE_AUTO_*` masters. `portfolio_actions` is clean only incidentally. AGENTS.md §13 requires the exclusion before any inference read.
1. **BUY leg still −500bps.** New-gate BUYs (dislocation + factor agreement) are open; if they close red, add Beneish/accrual veto before any timing tweak (timing already proven dead). Needs 09-21/09-22 EOD ingested first (CSVs already on disk).
2. **Small/micro cells n=0.** Needs call rows (screener over small/micro dates) + hierarchical shrinkage; micro 50bps-impact assumption needs slippage measurement first.
3. **SELL holding periods.** The 1–7d "target" exits never happened (artifact). Honest recompute: ~0 at 1–3d, +790bps at 20d on 5 clusters. Test OU half-life holds vs fixed exits **after** the framing fix.
4. **Calibration on the new regime.** Folds predate the SELL book; re-run after P0 (the previous "SELL dominates wins" premise was the artifact). Consider bandits if batch folds keep refusing.
5. **Substrate versioning.** moat/ENI/ripple lack history columns — true delta predictors unobservable; add versioning so flows can vote honestly (prerequisite for T2's "flows VOTE" half).
6. **Slippage audit.** Measure realized slippage vs the 50bps prior; shrink it with data (mechanism-design lens).
7. **Benchmark coverage.** Only 50 masters `is_nifty50=1`, 5,909 are the MICRO default bucket, 101 LARGE non-Nifty50 silently `unmapped-universe`. Print per-universe n + the unmapped list with every excess table.
8. **Test-suite speed.** 738 passed but 199s under xdist (contention-bound); serial-profile bootstrap ~60s first — see `tasks/test_perf_baseline_2026-09-22.md`.

## Promotion log

| Date | Strategy | Evidence | Decision |
|---|---|---|---|
| 2026-09-23 | SELL widened broken-thesis + realized-window excess | 46/46 closed SELLs exited at `exit_price == stop_loss` with pnl == exactly `|stop%|`; all 5,139 call rows are long-framed (`×1.18/×0.94`); +527bps reproduces only with the artifact fill, −20bps on market closes | **REVOKED** — artifact; re-test after terms-layer framing fix |
| 2026-09-22 | SELL widened broken-thesis + realized-window excess | 46/46 wins; +527bps n=34 hit 1.00, 6 cohorts | ~~PROMOTED to gate-passing leg~~ (revoked 2026-09-23) |
| 2026-09-22 | Predictor honesty + dislocation + factor gates | 58 + 25 tests green; live probes match | PROMOTED to production resolver |
| 2026-09-22 | Confirmation filter | 1W/29L stabilized; 0W/14L skipped | REJECTED, do not revisit |
| 2026-09-22 | Original BUY (lone residual) | 44 closed, 1 win, −500bps | DEMOTED to baseline; gated variants under test |
