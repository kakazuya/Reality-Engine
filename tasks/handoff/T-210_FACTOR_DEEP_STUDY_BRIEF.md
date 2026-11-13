# T-210: factor-reward deep study (T-207 round 3): sectors, companies, combinations, opposites

Ticket: T-210

Goal: Shivam 14 Nov: go deep. Measure which factors are rewarded per SECTOR and per COMPANY (not only the universe),
at 6 / 12 / 24 months, point in time; find factors that work TOGETHER (combinations, interactions), factors that are
OPPOSITE (negatively correlated exposures or rewards), and prune factors that add nothing once the others are known.
Add a sector-KPI arm. Same honesty rules as T-207: only returns realised by the date, thresholds fixed in this brief
before any result is seen, walk-forward, placebo, multiplicity.

Evidence (checked by Claude 14 Nov):
- T-207 engine: `reality_engine/research/factor_rewards.py` (realised_ic, build_ic_table, rewarded_at, sector_map,
  add_size_buckets, regime_labels, walk_forward, permute_panel, placebo_counts, bh_survivors) on the panel of
  ``build_panel` in reality_engine/research/factor_weights.py` (35 factors, 2,253 companies, 71 month-ends 2021-01..2026-11,
  snapshot `truth_2026-11-04.duckdb`, memory_limit 5 GB). Report `docs/research/T-207_factor_rewards.md`: six factors
  stable at all horizons (insider net buy, earnings yield, log P/E, own 5y margin and PAT percentiles, promoter 1q);
  24m dynamic selection failed on stale signs (R2.5); 3 of 4 regime cells too thin. Reuse the engine: import, do not copy.
- Sector KPIs: `kpi_series` (columns symbol, metric, dimension, value, unit, scale, fiscal_period, as_of_date, basis,
  known_at ...) in the pilot stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/
  pilot10.db,aurobindo/aurobindo.db,bluestar/bluestar.db}`: 52 companies, median 25 periods, from 2022-12 (pilot10
  from 2024-12). Read with `reality_engine.db.readonly.connect_ro`. This arm is THIN by construction: label every
  result from it "method pilot, n companies, not a finding" unless it passes the same gates as the main arm.

Fixed in advance (do not change after seeing results; later additions are labelled as such):
- Sector groups as T-207 (>= 30 names per group-month); per-company estimates via partial pooling (empirical-Bayes
  shrinkage of the company's own time-series IC/beta towards its sector's, weight by the company's own sampling
  variance; companies with < 24 usable months are reported as sector-only).
- Correlations: per sector, the cross-sectional Spearman correlation of factor EXPOSURES at each month-end (mean over
  months), and the time-series correlation of the monthly factor ICs (do two factors' rewards rise and fall together,
  or oppositely). Report pairs with |rho| >= 0.5 as "move together" / "opposite"; clusters at |rho| >= 0.7.
- Redundancy: per sector and horizon, Fama-MacBeth multivariate regression with all non-clustered factors; a factor is
  "redundant" when its univariate reward is significant (T-207 rule) but its multivariate NW |t| < 1.5.
- Interactions: for every pair of factors (595) per sector and horizon, the IC of A within the top and the bottom
  tercile of B; an interaction is claimed when the difference has NW |t| >= 2.5 AND survives BH 10% across all pairs x
  sectors x horizons AND exceeds the 95th percentile of the same statistic over 20 within-date permutations of B.
- Combinations: per sector, a sparse score chosen by forward stepwise (max 6 factors, add only if trailing-window IC
  rises by >= 0.005) using only data known at t; compared in walk-forward against the T-207 EQUAL convention score and
  the universe DYNAMIC score. Never search all subsets.
- Placebo: 20 fixed-seed permutations for every claim type; report observed vs placebo counts.

Steps:
1. `reality_engine/research/factor_deep.py` + tests `reality_engine/tests/test_factor_deep.py` (synthetic panels with
   a planted interaction, a planted opposite pair, a planted redundant factor and a planted company-specific factor;
   each must be found; a pure-noise panel must yield no claims beyond placebo).
2. Run on the full panel; outputs under `--out .tmp/t210/` (csv per table). Runtime target under 2 hours; measure the
   first sector before launching all and print the projection.
3. KPI arm: build a company x quarter KPI-factor panel (level, YoY change, change in YoY) for metrics with >= 8
   companies in a sector group; same IC / interaction tests at 6 and 12 months; label as method pilot.
4. Report `docs/research/T-210_factor_deep_study.md`: per sector the rewarded factors, pairs that move together,
   opposites, redundant factors, interactions that survive, the sparse combination and its walk-forward vs EQUAL and
   DYNAMIC; per company a table (top 200 by months of data) of factors where the shrunk estimate differs from its
   sector's; what was too thin. Plain words first, numbers beside. Shivam reads it.
5. Docs: DEVELOPER_GUIDE block; PROGRESS_NOTES line per step.

Files: `reality_engine/research/factor_deep.py`, its test, the report, DEVELOPER_GUIDE. Read-only: the snapshot and stores.
Test command(s): python -m pytest reality_engine/tests/test_factor_deep.py reality_engine/tests/test_factor_rewards.py -q
Accept: tests pass; report exists with every table above and its placebo/multiplicity lines; typecheck clean.
Pitfalls: overlapping horizons make t-values optimistic (lags = h-1 months); a sector with few names reaches 70% by a
handful of months (say so); never pool regimes; company time series at 24m are ~3 independent windows (say so); no
look-ahead in shrinkage (sector prior from data known at t only); memory: chunk by sector, RAM must stay < 90%.
RAM (14 Nov 00:10): only 3.6 GB of 16 GB free; three other workers run. Build and run the synthetic tests first; start
the panel run only when free RAM >= 7 GB (check with PowerShell `Get-CimInstance Win32_OperatingSystem`), re-checking
every 10 minutes for up to 90 minutes; if still short, stop after the tests and say so (Claude reruns it).
Stop if: the T-207 reproduction (its section 2 table) does not match to 0.001; projected runtime > 4 hours; 5 hours.
Budget: 5 hours, 400 tool calls.
