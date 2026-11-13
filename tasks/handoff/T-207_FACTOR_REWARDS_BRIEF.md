Ticket: T-207

Goal: round 1 of the factor-reward engine. For every month-end, measure which held factors were being rewarded over
6, 12 and 24 months, using only returns that had already been realised on that date; report the rewarded set, how often
each factor is in it (the mode), the dates the set shifts, by sector group and market regime; and test walk-forward
whether choosing factors this way beats a fixed choice.

Why (read this first): the project's end goal is to predict a stock 6 months to 2 years ahead from the least data.
T-118 (`docs/research/T-118_factor_weights.md`, read sections 1, 2, 7 and 8) measured each factor once over the pooled
2021-2026 sample. Shivam ruled on 10 Nov that factor rewards are not fixed laws: they must be recomputed at every point
in time per stock, sector and regime, and the report is the statistical mode of rewarded factors and its shifts. A
pooled average also uses the future: on any past date nobody knew the 2021-2026 average. The result of this study
decides which document extraction is worth finishing, so an honest "this factor is not stably rewarded" is as useful as
a positive finding.

Evidence (T-118, pooled, 2021-01 to 2026-10; these are the numbers your first step must reproduce):
- TTM earnings yield: mean monthly rank IC +0.056 / +0.071 / +0.098 at 6 / 12 / 24 months.
- Own 5-year margin percentile +0.052 / +0.066 / +0.081; promoter % change over 4 quarters +0.032 / +0.050 / +0.066.
- 12-1 momentum +0.067 at 6 months; 1-month reversal -0.051 at 12 months.
- Panel: 93,057 company-months, 2,266 companies, 83 month-ends; 2020 excluded from statistics (growth coverage 12%).
- Period split already hints at instability; it is in `.tmp/t118/factor_ic.csv` when the T-118 run is repeated.

Files: new `reality_engine/research/factor_rewards.py`, new `reality_engine/tests/test_factor_rewards.py`, new
`docs/research/T-207_factor_rewards.md`, one line in `tasks/STATE.md`. `reality_engine/research/factor_weights.py` is
imported, not changed (its 22 tests must still pass). Snapshot, read-only:
`C:/Users/warri/Downloads/Info_Diffusion_Model/reality_engine/data/snapshots/truth_2026-11-04.duckdb` (the 2026-11-09
file holds prices only; do not use it). Outputs only under `.tmp/t207/` in your workspace.

Steps:
1. Build the panel with `factor_weights.build_panel` (DuckDB `memory_limit` 5 GB, as T-118 runs it) and save it once
   as parquet under `.tmp/t207/` so later steps do not rebuild it. Reproduce three of the pooled ICs above to two
   decimals before going on; if they do not match, stop and report.
2. Realised IC series: for factor f, horizon h and month-end s, the rank IC of f at s against the forward excess return
   from s. This IC is KNOWN only from the date the horizon ends (s + 126 / 252 / 504 sessions). Store that
   `known_date` with every IC.
3. Rewarded set at date t: over the trailing 24 months of ICs whose `known_date` <= t (also run 12 and 36 months as a
   sensitivity), a factor is rewarded when the mean IC has |Newey-West t| >= 2 and the sign of the mean matches the sign
   in at least 60% of those months. Record sign, mean IC, t and months used. Fewer than 12 known months: not rated.
4. Splits, each computed the same point-in-time way: (a) all companies; (b) sector groups from `company_industry`,
   merged until each has at least 30 names a month (report the merge); (c) size terciles; (d) market regime known at
   the month-end s: Nifty 500 TRI above or below its 200-session average, and trailing 12-month TRI return positive or
   negative (two labels, four cells; if a cell has fewer than 12 months, report it as too thin, do not pool silently).
5. Mode and shifts: per horizon and split, the share of rated months in which each factor is rewarded (with its sign),
   the factors rewarded in at least 70% of months, and every date a factor enters or leaves the set or flips sign.
6. Walk-forward test, per horizon: at each month-end t build three scores per company: DYNAMIC = sum of sign x z of
   the factors rewarded at t (step 3, all companies); STATIC = the same sum over the factors rewarded in the FIRST
   rated window only, frozen; EQUAL = the sum over all factors with the sign fixed in advance from finance convention
   (state the convention in the doc). Then measure each score's realised IC and top-minus-bottom fifth excess return
   over the next h, on months after the first rated window. Report mean, Newey-West t, hit rate, number of months, and
   the paired difference DYNAMIC minus STATIC with its t.
7. Count every (factor, horizon, split) cell tested and apply Benjamini-Hochberg at 10% to the step-5 claims; the doc
   states how many cells were tested and how many survive.
8. Tests on synthetic panels (no snapshot needed): a planted factor whose reward flips sign halfway is rewarded
   before, unrated or unrewarded around the flip, and rewarded with the other sign only AFTER the horizon has passed;
   an IC whose `known_date` is after t never enters the window at t (plant a huge value and assert the result is
   unchanged); a factor with fewer than 12 known months is not rated; DYNAMIC equals STATIC when nothing changes.
9. `docs/research/T-207_factor_rewards.md`: method in one page, the tables of steps 5-7, what is stable, what shifted
   and when, what is too thin to say, and a short list "extraction worth finishing / not shown to matter" that follows
   only from the tables. List the factors still unmeasured because the snapshot lacks them (ROE and ROCE, promoter
   pledge, FPI and mutual-fund holding change, guidance raised or cut) with the table each would need.

Pitfalls: overlapping horizons make t-values optimistic (Newey-West lags = horizon in months - 1; at 24 months treat t
as an upper bound and say so); pandas 3 stores datetimes in microseconds (T-118 hit a 1970 date bug; reuse its date
helpers); sector-median factors have no within-sector z; the index series ends 2026-10-16, so the last months have no
target; shareholding `known_at` before 2022 is a backfill, so promoter factors are empty before 2022 by design; 24-month
results rest on about 45 known months, so trailing windows there are short: report the month counts beside every figure.

Accept: `python -m pytest reality_engine/tests/test_factor_rewards.py reality_engine/tests/test_factor_weights.py -q
--basetemp=.tmp/pt1` passes; `python -m reality_engine.research.factor_rewards --out .tmp/t207` runs end to end in
under 15 minutes and writes `rewarded_by_date.csv`, `mode.csv`, `shifts.csv`, `walk_forward.csv`; the doc exists; the
final answer gives the walk-forward table, the factors rewarded in at least 70% of months per horizon, the number of
cells tested and surviving, and a `Docs updated:` line.

Stop if: step 1 does not reproduce T-118; the run needs more than 6 GB of memory (report the step; do not raise the
limit); any change would write to the snapshot or to a database; a step needs data the snapshot does not hold (list it
under "unmeasured", do not fetch). Do not tune thresholds after seeing the walk-forward result: the thresholds above
are fixed for this round, and sensitivities are reported beside the main result, never substituted for it.

Budget: 3 hours, about 180 tool calls. Do not commit PROGRESS_NOTES.md or anything under `.tmp/`.
