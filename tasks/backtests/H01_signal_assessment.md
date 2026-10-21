# H01: keep the longer-term selection lead in research

**H01 should remain in research.** The extension found a useful earnings-label association around180 trading sessions. It has not produced a deployable standalone book under the current risk limits.

## What longer holding periods changed

Positive-PAT, both-known entry policy, all nonzero positive surprises. Returns below are mean event excess over after-tax/cost B5, not book CAGR.

| Hold, regular sessions | Mean excess | Median excess | Events |
|---:|---:|---:|---:|
| 90 | +2.57% | -0.41% | 5,041 |
| 120 | +5.17% | +0.73% | 4,641 |
| 180 | +8.78% | +2.29% | 4,285 |
| 252 | +16.67% | +4.67% | 3,906 |
| 504 | +44.70% | +15.09% | 2,194 |

The same early-entry sample also rises from+0.56% at20 sessions to+2.58% at60,+6.69% at120,+11.20% at180,+21.57% at252 and+44.70% at504. The shape is therefore not solely caused by later entries dropping out of longer windows.

The within-month date placebo retained the stock identities and their earnings scores. It performed equally well or better. That weakens a claim about precise announcement timing; it does not test whether earnings labels discriminate between stocks.

## The useful selection result

A separate, predeclared10-test follow-up shuffled PAT labels within entry month, prior200-session trend and lagged20-session liquidity strata. Prices, dates and issuer identities stayed fixed. Positive and negative controls needed at least3 observations per cell, weighted by the smaller leg count.

At180 sessions, the broad positive-PAT cohort had+7.95% matched mean excess; negative-PAT controls had+3.46%. The **difference is+4.49 percentage points**, across6,544 matched observations and132 cells. This contrast is a research association, not a tradable long-short return.

- Entry-year differences were positive in2022,2023,2024 and2025.
- Matched evidence spans27 entry months;2025 contributes only2 months. This is a thin fourth period, not a full-year confirmation.
- Cluster p=.00038; horizon-aware monthly HAC p=.00202.
- BH q=.0335 across all216 recorded tests, including earlier failures and corrections.
- Label-placebo p=.001 from999 coherent permutations; current10-test max-T p=.009.
- The largest5 issuers contributed6.06% of matched positive payoff mass. The result is not concentrated in those5 names.
- No source unexplained-jump flags cross any both-known180-session outcomes.

Stronger surprise thresholds did not improve the matched association reliably. At180 sessions, absolute surprise>=1 gave+3.25points but BH q=.553; at504 it gave-1.76points. Keep the broad positive-versus-negative earnings distinction as the current research lead rather than selecting the largest score after seeing returns.

## What prevents deployment

All94 positive books in the longer-horizon grid hit the unchanged8% strategy drawdown kill. Their losses remain the book evidence. The larger unmanaged event returns do not authorize holding a killed allocation or relaxing FRAMEWORK.

The252-session sample covers only2022–2024 entries and504 covers2022–2023. Their impressive averages are not four independent years of proof. The504 HAC check refuses precision. Sector and market-cap confounding remain uncontrolled because no point-in-time control was invented. Issuers recur across quarters, outcomes overlap, and full source-data coverage is incomplete. B5 still has a previous-close entry proxy and derived BSE total-return series; tax is the snapshot base capital-gains model.

The practical next research step is a registered challenger that uses the broad earnings distinction in stock selection and tests how to survive adverse regimes under the existing risk limits. This result does not yet authorize a live selection model, parameter search, risk-limit change or2026-based tuning.

## Work and verification

- Long grid:174 declared tests,499 date permutations,84,423 unique compressed outcomes,94 positive books; run03f51f86-ee1c-4e9f-af61-b67905a0817c,109.1seconds.
- Selection follow-up:10 declared contrasts,999 label permutations; run3ccfe910-8d7c-4e54-8aaa-ac622cb521ca,9.5seconds.
- Final combined suite:97 tests passed. Long-grid independent review:28 checks passed. Selection independent review:14 checks passed, including pandas cell reconstruction, the first3 coherent null draws, source lagged liquidity, and the full216-test BH family.
- The snapshot was read-only and unchanged. The corrected20/60 report is preserved. No2026 outcomes, paid worker, commit, push or upload.
- Resource note: initial unittest discovery repeated10 imported fixture tests. The import was corrected and the final suite is97 tests. The long run used about1.6GB resident RAM and2 DuckDB threads. Compressed outcome/book audits use about11MB.

Full detail: H01_long_report.md, H01_long_results.json, H01_long_verification.json, H01_selection_report.md, H01_selection_results.json and H01_selection_verification.json in this directory. Frozen plans are in tasks/codex_tasks/H01_LONG_HORIZON_PLAN_2026-10-21.md and H01_SELECTION_FOLLOWUP_PLAN_2026-10-21.md.
