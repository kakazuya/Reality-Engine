# H01 longer-horizon follow-through — declared before results, 21 October 2026

Shivam asked to let H01 run over longer time frames and check for a usable signal before culling it. This supersedes moving immediately to H02. Peak-time Codex implements and verifies; no paid worker start.

Source and constraints remain the same read-only truth_2026-10-19.duckdb, evidence 2021–2025, 2019–2020 warm-up, no 2026 outcomes, cash long only, 30bp round trip, sell-date tax, B5, liquidity cap and 8% strategy drawdown kill. Longer holding periods do not waive the book risk limits.

## Frozen grid

Primary: 2 PIT entry policies (strict BSE next open, both-known next open) × 5 horizons (90,120,180,252,504 regular sessions after entry) × 2 measures (PAT,revenue) × 2 signs (positive long, negative avoid) × 4 cohorts = **160 tests**.

Cohorts: any nonzero surprise; absolute standardized surprise >=1; absolute surprise >=2; absolute surprise >=2 plus prior-known price trend. Positive trend confirmation requires last completed close above its trailing200-session arithmetic mean; negative avoid confirmation requires below it. No thresholds are fitted to this run. Missing trend history refuses the trend cohort. Large absolute surprises from negative earnings bases are not automatically called high quality.

Matched-entry diagnostic: both-known PAT positive, cohorts any and >=2+trend, horizons20,60,90,120,180,252,504; every entry must have room for504 sessions within2025. **14 additional tests**, not an unlogged scan. These compare the same entry opportunity set; report all counts and any delayed exits.

Total new grid: **174**, plus all prior32 ledger tests for initial BH family206. All pass/fail tests are appended; no pruning from the family.499 within-month timestamp permutations recompute PIT/liquidity/trend eligibility/entries/actual exits. Current-grid max-T covers174 tests; historical tests remain in BH. Long-horizon overlapping outcomes have low effective sample size: report entry-month-clustered tests plus a conservative horizon-lag HAC check on monthly cohort means. Report yearly signs, market regimes and event counts;504-session tests cannot provide four independent entry years in this snapshot and cannot pass that proof rule.

## Deliverables and judgement

Separate H01_long report/results, compressed outcome audit, tests and verification. Preserve the corrected20/60 report. Report raw/net stock return, matched after-tax B5 excess, median, probability of positive excess, entry years, industry-independent issuer count, tax status, false-discovery/placebo checks and all positive books. Classify evidence as a research lead vs proven deployment candidate; do not kill the entire H01 idea merely because the broad20/60 book failed.

Any suggested follow-up must follow observed sign consistency, magnitude concentration, matched-entry curve, placebo performance and the actual constrained book. No claim of deployment readiness without data completeness and the Framework's proof/risk rules. Log timing/resource problems honestly. No commits, pushes, uploads, source database writes or parameter tuning after seeing this run.
