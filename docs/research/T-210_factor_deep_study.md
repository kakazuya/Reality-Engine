# T-210: factor-reward deep study (T-207 round 3)

Study for ticket T-210 (Shivam, 14 Nov). Round 1 (`docs/research/T-207_factor_rewards.md`) asked
which factors were rewarded at each month-end, using only returns already realised. This round goes
deep: the same question **inside each sector group**, per single company (shrunk to its sector's
estimate), then the questions a per-factor list cannot answer — which factor exposures are the same
bet, which rewards rise and fall together or oppositely, which factors stop adding anything once the
others are known, which factor pairs only work together, and whether a sparse per-sector combination
beats the fixed EQUAL convention and the universe DYNAMIC choice out of sample. A sector-KPI arm on
the pilot stores is a labelled method pilot.

Code `reality_engine/research/factor_deep.py`, tests `reality_engine/tests/test_factor_deep.py`
(13 tests, all synthetic). It imports the T-207 engine (`factor_rewards.py`) and the T-118 panel
builder (`factor_weights.py`) unchanged — no copy of either.

```bash
python -m pytest reality_engine/tests/test_factor_deep.py reality_engine/tests/test_factor_rewards.py -q   # 24 passed (64-101 s under three-worker load)
python -m reality_engine.research.factor_deep --out .tmp/t210 --project   # one sector, print projection
python -m reality_engine.research.factor_deep --out .tmp/t210             # full run
```

**Run status: not started.** The brief's RAM gate is 7 GB free and the panel build reads the dated
DuckDB snapshot with a 5 GB memory limit. Free physical memory on this host was sampled once a minute
for the brief's 90-minute limit (89 samples, 00:12-01:42 on 14 Nov) and ranged **2.6-4.7 GB of
16 GB**, never close to 7 GB, with three other workers active. The brief says in that case: stop
after the tests and say so; Claude reruns the panel. So this document fixes the design, proves the
machinery on planted synthetic panels, and states exactly what the rerun must produce and where.
**It contains no result numbers, because none were computed.** The CSVs under `.tmp/t210/` are the
deliverable of the rerun; sections 5-6 are the contract they must fill.

## 1. What is fixed before any result (brief, 14 Nov)

| item | fixed value |
|---|---|
| horizons | 6 / 12 / 24 months (126 / 252 / 504 sessions), T-207's |
| sector groups | T-207's `sector_map` output: a sector stays its own group with >= 30 names in >= 12 months, else folded into "Other (merged)"; sector ICs use only >= 30-name months |
| main reward window | 24 trailing months of realised ICs; rewarded = NW \|t\| >= 2 and 60% sign share; < 12 known months not rated (T-207 rule, reused) |
| correlation "moves together" / "opposite" | mean cross-sectional Spearman \|rho\| >= 0.5; cluster at \|rho\| >= 0.7 |
| redundancy | univariate reward significant (T-207 rule on the sector's full IC series) but joint Fama-MacBeth NW \|t\| < 1.5 |
| interaction claim | NW \|t\| >= 2.5 on IC(A \| top tercile of B) - IC(A \| bottom tercile of B), survives BH 10% across all pair x sector x horizon cells, and beats the 95th percentile of 20 seeded within-date permutations of B || combination | forward stepwise, at most 6 factors, add only if the trailing-window (24 realised months) IC rises by >= 0.005; only data known at t; no subset search |
| company floor | 24 usable months for a company's own estimate, else sector-only |
| KPI arm | a metric needs >= 8 companies in a sector group; 6 and 12 months; labelled method pilot |
| placebo | 20 fixed-seed permutations for every claim type (seed 20261114) |

The implementation adds three bounds that are not result thresholds and are named here so the rerun
does not read them as after-the-fact choices: the stepwise candidate pool is the factors with
trailing \|IC\| >= 0.02 capped at the 8 strongest (else the top 8 by \|IC\|); the joint model keeps
factors with >= 80% non-null coverage inside the sector and at most 8 regressors (a complete-case
OLS on a 30-name sector cannot carry thirty); "differs from its sector" for a company is
\|shrunk - prior\| >= 0.10. A combination claim is sparse minus **both** baselines with paired NW
\|t\| >= 2 over >= 12 test months, at **12 months** (6m and 24m are reported descriptively: 24m has
8 test months in total, so it cannot reach 12).

## 2. How each arm works, in words

**Sector rewarded set.** Same arithmetic as T-207, applied to sector-group ICs: at each month-end,
the reward state of every factor over realised ICs whose forward window had closed by that month-end
(`known_date` = rebalance + horizon sessions). Nothing new is asserted about which factors are
rewarded in a sector; the result is the sector cut of the same test, with BH across every rated cell.

**Exposure correlation.** At each month-end, within a sector, the pairwise-complete Spearman
correlation of the 35 raw factor values (so a bank whose margin factors are blank does not delete the
whole row). Averaged over months, per sector. A pair at \|rho\| >= 0.5 is printed as "moves together"
or "opposite"; pairs at \|rho\| >= 0.7 are joined by connected components into one cluster. This is a
description of the bets, not a claim about returns.

**IC correlation.** The same pair logic on the monthly IC series per sector and horizon: do the two
factors' rewards rise and fall together (positive rho), or does one being rewarded mean the other is
not (negative)? Months with a missing IC are dropped pairwise.

**Per-company shrinkage.** For each company and factor, the time-series rank IC over the months
whose forward window had closed by the last month-end (no look-ahead: the estimate at the table's
as-of date uses only returns realised by it). Each company's sampling variance is
`s^2 = (1 - r^2)/(n - 2)`; the sector's between-company variance `tau^2` is
`max(0, var(company ICs) - mean(s^2))` over the sector's companies with >= 24 months; the shrunk
estimate is `w*own + (1-w)*prior` with `w = tau^2/(tau^2 + s^2)`. A company under 24 months is
reported sector-only (`w = 0`). The reportable gaps are the ones where the shrunk estimate is
materially away from the sector prior — the question "is this company different, after allowing for
noise and for its sector?", not "which company has the noisiest IC".

**Redundancy.** Within a sector and horizon, a monthly cross-sectional OLS of the forward excess
return on the within-date z of the model's factors, then Newey-West on each coefficient series. The
model's factors are one representative per exposure cluster (the cluster member with the strongest
univariate \|t\|), coverage-filtered and capped as above. A factor whose univariate reward is
significant but whose joint \|t\| is < 1.5 is called redundant: once its neighbours are known it
adds nothing measurable. Factors kept out of the model by the cluster rule or by coverage are
reported as *not tested*, never as redundant.

**Interactions.** For each unordered pair (595 of 35 factors) the cross-section is split into terciles
of B (the later factor in `FACTORS` order) and A's rank IC is measured inside the top and the bottom
tercile; the monthly difference is the statistic. The orientation is fixed by `FACTORS` order (A is
the earlier factor), so a claim reads "A pays off conditionally on B"; the direction is in the sign
of the mean difference. Terciles need 20 names each, so a sector-month with fewer than 60 names is
not tested and contributes no cell to the BH family. The three gates are the brief's: \|NW t\| >= 2.5,
BH 10% over every pair x sector x horizon test, and above the 95th percentile of the same statistic
over 20 within-date permutations of B (A and the target stay real; only B's assignment moves). The
permutation null also yields the placebo claim count per run with the same gates and BH — that is the
"observed vs placebo" line for this claim type.

**Combinations.** At each month-end t, per sector, the stepwise search sees only months whose
forward window had closed by t; it starts empty, and at each step adds the candidate whose signed
composite (sign = that factor's trailing univariate IC sign) gives the highest trailing-window IC,
accepting only an improvement of at least 0.005, to a maximum of 6 factors. The chosen score is then
measured on the **next** month's realised excess return and compared with the EQUAL fixed-convention
score (T-207's signs) and the universe DYNAMIC set (T-207's all-companies rewarded set at t) applied
inside the same sector. The monthly series and the paired NW differences are the evidence.

**KPI arm.** Seven pilot stores' `kpi_series` are read read-only (`connect_ro`), the fiscal label is
turned into a quarter index, and per symbol x metric x dimension the arm builds the level, the YoY
change (against four quarters earlier) and the change in YoY. The exposure is paired with the first
month-end on or after its `known_at` and the forward excess return of that month; the same rank-IC
and tercile machinery runs cross-sectionally at 6 and 12 months, gated at 8 companies in a sector
group (6 names for the pooled IC). 52 companies is the whole arm; anything it reports is
"method pilot, n companies, not a finding" unless it passes the main arm's gates, which it cannot at
this sample size.

## 3. Synthetic validation (13 tests)

Each planted effect is a small deterministic panel of 160 companies in two sectors over 40 months
(30 for the stepwise timing test), with a real NSE-like business-day calendar so the horizon
arithmetic is exercised. Pass/fail, not eyeballing:

| test | planted thing | assertion |
|---|---|---|
| `rank_ic` / `avg_ranks` | an exact order and ties | +1 / -1 vs the planted order; average ranks on ties; thin samples NaN |
| opposite pair | `opp = -f1` | exposure rho <= -0.5, relation "opposite", `f1` and `opp` in one cluster |
| redundant factor | `f5` proxies `f1` (rho ~0.6, below the cluster rule) while only `f1` pays | `f5` univariate-significant, joint \|t\| < 1.5, flagged redundant; `f1` joint \|t\| >= 1.5 |
| company-specific factor | one company's `f1` relation reversed | own IC < -0.3, sector prior > 0.3, shrunk still materially below the prior, gap reportable, a peer within 0.10 of the prior |
| no look-ahead in a company estimate | a cut before the horizon closes | no company reaches the 24-month floor -> empty |
| interaction | `sig` pays only when `cond` is high | the `sig`/`cond` cell is claimed, mean difference > 0.3, \|t\| >= 2.5 |
| pure-noise panel | targets independent of every factor | no interaction claim beyond the placebo runs' own count |
| stepwise | an independent three-factor target | picks `f1` (+), `sig` (-), ignores `noise`; IC gain >= 0.005 |
| candidate pool | 30 candidates | capped at 8, strongest kept |
| walk-forward timing | targets after month 20 flipped | every pick at t <= month 20 is byte-identical (only realised months enter) |
| fiscal labels | `Q2FY26`, `H1 FY25`, `9M FY25`, `FY24` | quarter indices; `kpi_factor_panel` gives YoY 200/100-1 and change-in-YoY 0.5-1.0 at the right rows |

`python -m pytest reality_engine/tests/test_factor_deep.py reality_engine/tests/test_factor_rewards.py -q`
-> **24 passed** (13 new + 11 T-207; 64-101 s under three-worker load). No snapshot, no pilot store,
no network.

## 4. What the rerun produces (the tables the ticket asks for)

Every table is written under `--out` as CSV; this is the contract, with the columns that carry the
answer. The report's numbers go beside each table after the run.

| file | rows | the question it answers |
|---|---|---|
| `sector_mode.csv` | factor x sector x horizon | rewarded in >= 70% of rated months? share, sign, mean IC, median \|t\|, rated months, BH survival |
| `sector_claims.csv` | the same, claims only | which sector claims survive BH (with the exact binomial p) |
| `corr_exposure.csv` / `corr_exposure_pairs.csv` | sector x 595 pairs | mean cross-sectional rho, relation ("together"/"opposite"), cluster id |
| `corr_ic.csv` / `corr_ic_pairs.csv` | sector x horizon x 595 pairs | time-series rho of monthly ICs, relation, cluster |
| `univariate_sector.csv` | sector x horizon x factor | full-series mean IC, NW t, sign share, significant? |
| `fama_macbeth_sector.csv` | sector x horizon x model factor | joint coefficient, NW t, months, mean names |
| `redundancy.csv` | sector x horizon x factor | univariate t, in model?, clustered out?, joint t, redundant? |
| `company_own_ic.csv` / `company_shrunk.csv` / `company_gaps.csv` | company x factor x horizon | own IC, sampling variance, sector prior, weight, shrunk IC, sector-only flag; gaps reported |
| `interactions.csv` | sector x horizon x 595 pairs | mean difference, NW t, months |
| `interactions_null.csv` | x 20 runs | the permutation null per pair (the percentile gate and the placebo count) |
| `interaction_claims.csv` | survivors | the three gates, with p, BH flag, placebo percentile |
| `sparse_monthly.csv` / `sparse_summary*.csv` | sector x test month / sector | sparse, EQUAL, DYNAMIC IC; paired differences and t; the selected set each month |
| `placebo.csv` | claim type | observed vs 20-run mean/max for: sector stable-70 cells, interaction claims, sparse-beats-both |
| `kpi_panel.csv`, `kpi_ic.csv`, `kpi_interactions.csv`, `kpi_coverage*.csv` | KPI series / cells | level, YoY, change-in-YoY; ICs and tercile differences with the company counts (method pilot) |
| `t118_reproduction.csv`, `sector_groups.csv`, `factor_coverage_sector.csv` | gates | the panel gate, the sector merge, per-sector coverage |

The panel gate is T-207's: the five pooled T-118 ICs must reproduce to < 0.005, else the run stops
before any table (the brief's stop rule). The report section "per sector rewarded factors / pairs /
opposites / redundant / interactions / sparse vs EQUAL and DYNAMIC / per-company top 200 / what was
too thin" is written from these files after the run; the prose skeleton for the sector cut is
section 4 of `docs/research/T-207_factor_rewards.md`, which this round answers sector by sector and
then pair by pair.

## 5. Limits this study states in advance

- **Overlapping horizons.** 6/12/24-month forward windows overlap, so Newey-West t-values are
  optimistic even with lags = h - 1 months (5 / 11 / 23). The 24m t is an upper bound: at most 24 ICs
  in the window, 23 lags. The BH survival count is lenient for the same reason and is reported as
  lenient, never as a clean false-discovery rate.
- **Thin sectors reach 70% on a handful of months.** Realty and Metals & Mining have 12 and 11 rated
  6m/12m months in T-207, no 24m window; a 70% share on 12 months is 9 months. The report must say
  the month count beside every share, and the 24m sector cells for those groups are "too thin".
  The same thinness decides the interaction arm: a sector-month under 60 names cannot form two
  20-name terciles, so Metals & Mining, Realty and Textiles (30-48 names a month in T-207) get no
  interaction cells at all and the BH family shrinks to the sectors that do.
- **Company time series at 24m are ~3 independent windows.** 24 usable months of 24-month forward
  returns are almost perfectly overlapping; the shrinkage treats the point estimates as independent
  draws, which is wrong in the optimistic direction. Company 24m estimates are reported but called
  coarse.
- **`company_industry` is today's label.** Applying it to 2021 is a mild look-ahead (T-207 caveat);
  the sector cut is a diagnostic of where a reward is locally steady, not a tradable rotation.
- **The joint model is small.** Discrete factors (peak trap, delivery) and sparse ones (insider,
  promoter) enter only where a sector has 80% coverage; a sector whose model has too few complete-case
  months reports no joint t and its redundancy cells are "not tested". That is a data limit, not a
  finding of redundancy.
- **The KPI arm cannot be a finding.** 52 companies, metrics that mostly carry fewer than the 8
  companies the gate needs, so most cells will be empty; anything non-empty is method pilot.

## 6. Docs updated

`docs/DEVELOPER_GUIDE.md` (O19c block above this study), `tasks/STATE.md` (one line: built, tests
pass, run blocked on RAM), `PROGRESS_NOTES.md` (this worker's log). The T-207 report is unchanged
because T-207 is unchanged; this file does not restate its results.
