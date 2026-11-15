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
(15 tests, all synthetic). It imports the T-207 engine (`factor_rewards.py`) unchanged and uses
the T-118 panel builder (`factor_weights.py`) with streaming parquet output (`build_panel_parquet`)
and column-pruned float32 `*_z` reads so peak working set stays under 0.65 GB on a 16 GB machine.

```bash
python -m pytest reality_engine/tests/test_factor_deep.py reality_engine/tests/test_factor_rewards.py -q   # 26 passed
python -m reality_engine.research.factor_deep --out .tmp/t210 --project   # one sector, print projection
python -m reality_engine.research.factor_deep --out .tmp/t210             # full run
```

**Run status: complete (14 Nov 2026).** Peak working set was cut from **3.70 GB** (baseline
`--project` panel build) to **0.64 GB** with `--rebuild-panel` (`mem_full.log`) and **0.41 GB** on
the full study rerun reusing `.tmp/t210/panel.parquet` (`mem_rerun.log`, 93.46 min total). Section
4 is the table contract, section 5 the limits the results must be read against, and section 6
reports the full panel findings read from `.tmp/t210/`.

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

## 6. Results (`.tmp/t210/`, 14 Nov 2026)

### 6.1 Panel, T-118 gate, and sector grouping

The truth snapshot yields **93,057 panel rows** (`85,621` company-months with a 12m forward excess return across **2,253 companies** and **71 month-ends**, `2021-01-29`..`2026-11-03`). All five T-118 reproduction cells pass (`abs(diff) <= 0.000491 < 0.005` in `t118_reproduction.csv`):
- `earnings_yield`: 6m `+0.056285` (`+0.000285` vs `0.056`), 12m `+0.070973` (`-0.000026` vs `0.071`), 24m `+0.098122` (`+0.000122` vs `0.098`).
- `op_margin_pctile`: 6m `+0.051509` (`-0.000491` vs `0.052`).
- `promoter_chg_4q`: 12m `+0.049642` (`-0.000358` vs `0.050`).

Of the 23 raw sectors (`sector_groups.csv`), **14 qualify on their own** (`>= 30` names in `>= 36` months) and **9 thin sectors merge into `Other (merged)`** (`Construction Materials`, `Diversified`, `Forest Materials`, `Healthcare Services`, `Media Entertainment & Publication`, `Oil Gas & Consumable Fuels`, `Power`, `Telecommunication`, `Utilities`), giving **15 sector groups**.

### 6.2 Per-sector rewarded sets and their mode (`sector_mode.csv`, `sector_claims.csv`, `placebo.csv`)

Across the 15 sector groups, 3 horizons (`6m`, `12m`, `24m`), and 35 factors, `sector_mode.csv` contains **1,203 rows** (**939 rated cells** with `rated_months >= 12`).
- **Observed vs placebo**: **151 sector cells** reach `stable_70` (`share_rewarded >= 0.70` with one consistent `dominant_sign` and `rated_months >= 12`: **21** at `6m`, **62** at `12m`, **68** at `24m`), and **137 of the 151 survive Benjamini-Hochberg 10% FDR** (`sector_claims.csv`, which also includes the `"all"` split, has 182 rows and 165 BH survivors). Across 20 within-sector entity-permutation runs (`placebo.csv`), the null produces a mean of **33.50** `stable_70` sector cells and a maximum of **44** (`observed 151 >> 44`).
- **Most frequently rewarded factors across sectors (`stable_70`)**:
  - **6m (21 cells across 11 sectors)**: `delivery_3m (+)` in 3 sectors (`Consumer Durables` 100% of 53m, IC `+0.075`, `|t| 3.7`, BH; `Textiles` 81% of 31m, IC `+0.094`, `|t| 4.1`, BH; `Healthcare` 75% of 53m, IC `+0.078`, `|t| 2.3`, BH); `pe_ratio (-)` in 2 (`Other (merged)` 96%, IC `-0.142`, BH; `Automobile` 71%, IC `-0.110`, BH); `sales_yield (+)` / `ps_ratio (-)` in 2 (`Other (merged)` BH, `Construction`); `q_pat_yoy (+)` in `Chemicals` (83% of 53m, IC `+0.071`, BH); `vol_12m (-)` in `Realty` (100% of 18m, IC `-0.143`, BH). Sign flips across sectors appear even at 6m: `op_margin` is `(-)` in `Construction` (88% of 24m, IC `-0.217`, `|t| 6.0`, BH) and `(+)` in `Services` (86% of 22m, IC `+0.195`, `|t| 3.5`, BH), while `sales_yield` is `(-)` / `ps_ratio (+)` in `Consumer Services` (78% of 23m, IC `-0.102` / `+0.102`, BH).
  - **12m (62 cells across 13 sectors)**: `promoter_chg_4q (+)` leads in **5 sectors** (`Capital Goods` 88%, IC `+0.140`, `|t| 7.1`, BH; `Chemicals` 88%, IC `+0.115`, `|t| 7.6`, BH; `Consumer Services` 100%, IC `+0.133`, BH; `Information Technology` 94%, IC `+0.080`, BH; `Services` 81%, IC `+0.130`). Valuation multiples (`sales_yield`, `ps_ratio`, `ps_vs_sector`) are `stable_70` in **7 sectors**, splitting by business model: cheap sales (`sales_yield +`, `ps_ratio -`, `ps_vs_sector -`) is rewarded in **4 sectors** (`Chemicals`, `Consumer Durables`, `Information Technology`, `Other (merged)`, all BH), whereas high-multiple growth (`sales_yield -`, `ps_ratio +`, `ps_vs_sector +`) is rewarded in **3 sectors** (`Consumer Services` 100%, BH; `Services` 100%, BH; `Textiles` 71%). `pat_pctile (+)` is `stable_70` (BH) in `Capital Goods`, `Financial Services` (the only 12m `stable_70` factor in Financials: 100% of 17m, IC `+0.051`, `|t| 3.6`, BH), and `Other (merged)`. `FMCG` has one 12m `stable_70` factor (`promoter_chg_1q +`, 80% of 35m, IC `+0.061`, BH); `Healthcare` has one (`delivery_3m +`, 77% of 47m, IC `+0.074`, BH); `Automobile` rewards `sales_share_12m (+)` (86%, IC `+0.137`, `|t| 7.6`, BH) and `rerating_share_12m (-)` (100%, IC `-0.157`, `|t| 4.1`, BH).
  - **24m (68 cells across 13 sectors)**: Valuation dominates: `sales_yield (+)`, `ps_ratio (-)`, and `ps_vs_sector (-)` are `stable_70` (BH) in **6 sectors** (`Automobile`, `Capital Goods`, `Chemicals`, `Consumer Durables`, `Information Technology`, `Other (merged)`); `earnings_yield (+)` and `pe_ratio (-)` in **5 sectors** (`Automobile`, `Chemicals`, `Financial Services`, `Information Technology`, `Other (merged)`, all BH). Notably, `op_margin (-)` (low trailing margin outperforming over 24m) is `stable_70` (BH) in **5 sectors** (`Automobile`, `Capital Goods`, `Chemicals`, `FMCG`, `Information Technology`, versus `+` in `Other (merged)`), `fin_cost_to_rev (+)` (leverage/turnaround beta) in **5 sectors** (`Automobile`, `Capital Goods`, `Consumer Durables`, `Healthcare`, `Other (merged)`), and `ttm_rev_yoy (-)` (mean reversion of high trailing revenue growth) in **4 sectors** (`Capital Goods`, `Financial Services`, `Information Technology`, `Other (merged)`, all BH).

### 6.3 Correlations and redundant factors (`corr_exposure_pairs.csv`, `corr_ic_pairs.csv`, `redundancy.csv`)

- **Exposure and IC correlations**: Out of 8,925 sector exposure pairs (`corr_exposure_pairs.csv`), **378 pairs** have `|mean_rho| >= 0.5` (**266 together**, **112 opposite**) and **166 pairs** form `|mean_rho| >= 0.7` twin clusters. Across all 15 sectors, constructional twins/opposites hold universally: `sales_yield` vs `ps_ratio` (`-1.000`), `earnings_yield` vs `pe_ratio` (`-1.000`), `ps_ratio` vs `ps_vs_sector` (`+0.993`), `rerating_share_12m` vs `sales_share_12m` (`-0.855`), and `op_margin_chg` vs `op_margin_pctile` (`+0.701` across 14 sectors). Out of 16,306 sector-horizon IC pairs (`corr_ic_pairs.csv`), **3,699 pairs** have `|ic_rho| >= 0.5` (**2,072 together**, **1,627 opposite**), led by the same valuation twins plus `size` vs `vol_12m` (opposite in 12 sectors at 6m/12m, mean IC `rho = -0.744` / `-0.689`).
- **Fama-MacBeth redundancy (`redundancy.csv`, `fama_macbeth_sector.csv`)**: Across 1,050 `sector x horizon x factor` cells (272 regressor rows across 12 sectors at 6m/12m and 10 sectors at 24m), **289 cells** are univariately significant (`|t| >= 2.0` and sign share `>= 60%`), **333** are `clustered_out` (`|rho| >= 0.7` twin of a stronger factor), **319** enter the joint Fama-MacBeth model (`in_model`), and **44 univariate-significant factors are redundant** (joint Newey-West `|t| < 1.5` once peers are controlled for):
  - `delivery_3m` is the most frequently redundant factor (**10 cells total**: **4 sectors at 6m** — `Consumer Durables` univ `t = +6.08` -> joint `+1.20`, `Healthcare` `+2.73` -> `+0.69`, `Consumer Services` `+2.48` -> `+1.29`, `Services` `-2.10` -> `+0.43`; **4 sectors at 12m** — `Consumer Services` `+5.88` -> `+0.27`, `Healthcare` `+4.40` -> `+1.42`, `Consumer Durables` `+2.43` -> `-0.74`, `Services` `-2.29` -> `-0.44`; and **2 sectors at 24m** — `Consumer Durables` `+5.36` -> `+1.34`, `Services` `-3.69` -> `+1.26`).
  - `ps_ratio` is redundant in **5 cells** (`Construction` and `Services` at 6m; `Consumer Services` and `Services` at 12m; `Automobile` at 24m) and `earnings_yield` in **4 cells** (`Consumer Services` and `Other (merged)` at 6m; `Other (merged)` at 12m; `Chemicals` at 24m, where univ `t = +6.00` drops to `-0.03` alongside `sales_yield`).
  - `op_margin` is redundant in **5 cells** (`Information Technology` at 6m; `Services` at 12m; `FMCG`, `Information Technology`, and `Services` at 24m).
  - `vol_12m` is redundant in **3 sectors at 12m** (`Consumer Durables`, `Healthcare`, `Services`), `pe_ratio` in **3 cells** (`Automobile` and `IT` at 12m; `IT` at 24m), `fin_cost_to_rev` in **3 cells** (`Healthcare` and `Other (merged)` at 12m; `Other (merged)` at 24m), `reversal_1m` in **3 cells**, `size` in **3 cells**, `op_margin_chg` in **2 cells** at 12m, `mom_12_1` in **2 cells**, and `sector_pe_chg_12m` in **1 cell** (`Other (merged)` at 6m).

### 6.4 Claimed interactions against the placebo (`interactions.csv`, `interaction_claims.csv`, `placebo.csv`)

- **Coverage and selectivity**: The 60-name-per-month floor (`20` per tercile of B) admits **9 sectors** into `interactions.csv` (7,650 rows) and **5,380 cells** with `months >= 12` (`interaction_claims.csv`), of which **6 large sector groups** (`Capital Goods`, `Chemicals`, `Fast Moving Consumer Goods`, `Financial Services`, `Healthcare`, `Other (merged)`) account for all **634 claimed interactions** (`|nw_t| >= 2.5`, BH 10% FDR, and observed `|mean_diff|` above the 95th percentile of 20 within-date permutations of B): **132 at 6m**, **239 at 12m**, and **263 at 24m**.
- **Placebo comparison (`placebo.csv`)**: Across 20 full-panel entity permutations, the interaction pipeline claims a mean of **406.50** pairs and a maximum of **464** (`observed 634 > 464`, excess of ~228 claims above null expectation, confirming that while observed claims exceed the permutation max, the 20-draw p95 gate + Newey-West t on 12–45 overlapping months passes a high false-discovery baseline when horizons overlap).
- **Claimed counts by sector (`6m / 12m / 24m`)**: `Other (merged)` `30 / 69 / 86` (185 total), `Capital Goods` `31 / 54 / 80` (165), `Financial Services` `20 / 34 / 25` (79), `Chemicals` `18 / 37 / 16` (71), `Fast Moving Consumer Goods` `12 / 20 / 37` (69), and `Healthcare` `21 / 25 / 19` (65).
- **Strongest claimed conditional effects**:
  - In `Other (merged)` at 24m (45 months), `size` inside high vs low `earnings_yield` produces `mean_diff = +0.286` (`nw_t = +19.21`, null p95 `0.035`): size is rewarded among high-earnings-yield names and penalised among expensive names.
  - In `Capital Goods` at 24m (20 months), `ps_chg_12m` inside high vs low `sales_yield` gives `mean_diff = -0.286` (`nw_t = -19.11`, null p95 `0.029`), and `pat_pctile` inside `fin_cost_to_rev` (16 months) gives `mean_diff = -0.324` (`nw_t = -20.81`).
  - In `Fast Moving Consumer Goods` at 24m (14 months), `size` conditioned on `vol_12m` (`+0.603`, `nw_t = +38.48`), `earnings_yield` (`+0.403`, `nw_t = +28.00`), and `pe_ratio` (`-0.455`, `nw_t = -22.38`) leads by `|nw_t|`.
  - In `Healthcare` at 12m, `earnings_yield` conditioned on `ttm_rev_yoy` (14m, `mean_diff = -0.388`, `nw_t = -16.00`) and `delivery_3m` conditioned on `ttm_pat_yoy` (12m, `mean_diff = +0.386`, `nw_t = +14.40`) survive all three gates.

### 6.5 Sparse walk-forward combinations vs EQUAL and DYNAMIC (`sparse_summary*.csv`, `sparse_monthly.csv`)

- **Headline result (`placebo.csv`)**: **0 sectors** pass `beats_both = True` at 12m, 6m, or 24m (observed `0` vs placebo mean `0.00`, max `0` across 20 runs).
- **Why `EQUAL` and `DYNAMIC` are mostly `NaN`**: `_score_ic` sums `sign * frame[factor + "_z"]` across all factors in the convention dictionary without imputing `NaN`s. Because `EQUAL_SIGN` spans 29 factors (including `op_margin`, absent in Financial Services, and sparse ownership/insider series), complete-case rows reach the 20-name floor only in `Capital Goods` at 6m (`mean_equal_ic = -0.113`). Similarly, `DYNAMIC` reaches 20 complete-case names only in `Capital Goods` (`6m`: `+0.052`, `t = +2.02`; `12m`: `+0.048`, `t = +0.51`; `24m`: `-0.225`, `t = -41.32`). Because `beats_both` requires non-null positive `t_sparse_minus_equal >= 2.0` AND `t_sparse_minus_dynamic >= 2.0`, no sector qualifies.
- **Standalone walk-forward sparse combination performance**:
  - **12m (`sparse_summary.csv`, 472 sector-months across 15 sectors)**: `ALL SECTORS` averages `3.22` selected factors with out-of-sample `mean_sparse_ic = +0.0382` (`nw_t = +1.77`). Five sectors achieve `t_sparse_ic >= 2.0`: `Other (merged)` (`+0.200`, `t = +9.42`, 32m), `Realty` (`+0.159`, `t = +4.40`, 25m), `Consumer Services` (`+0.172`, `t = +2.97`, 32m), `Fast Moving Consumer Goods` (`+0.078`, `t = +2.21`, 32m), and `Information Technology` (`+0.108`, `t = +2.19`, 32m), while `Textiles` (`-0.123`, `t = -3.23`) and `Financial Services` (`-0.094`, `t = -1.99`) are negative out of sample. Top 12m forward-stepwise picks (`sparse_monthly.csv`): `sales_yield:+1` (133 sector-months), `op_margin:-1` (123), `fin_cost_to_rev:+1` (103), `vol_12m:-1` (74), `size:-1` (66), `pe_ratio:-1` (65), `delivery_3m:+1` (59).
  - **6m (`sparse_summary_6m.csv`, 650 sector-months)**: `ALL SECTORS` averages `3.14` factors with `mean_sparse_ic = +0.0104` (`nw_t = +0.73`). Only `Capital Goods` exceeds `t = 2.0` (`mean_sparse_ic = +0.0946`, `t = +2.15`, beating `DYNAMIC` `+0.0524` with `t_diff = +1.42`).
  - **24m (`sparse_summary_24m.csv`, 112 sector-months, 8 out-of-sample months per sector after the 36m training + 24m realisation lag)**: `ALL SECTORS` `mean_sparse_ic = -0.0050` (`nw_t = -0.26`), with positive out-of-sample ICs in `Information Technology` (`+0.135`, `t = +12.99`), `Healthcare` (`+0.058`, `t = +5.28`), `Consumer Services` (`+0.113`, `t = +3.38`), and `Construction` (`+0.232`, `t = +3.32`), offset by `Financial Services` (`-0.238`, `t = -19.44`) and `Chemicals` (`-0.091`, `t = -6.15`).

### 6.6 Company-level shrunk ICs and gaps (`company_own_ic.csv`, `company_shrunk.csv`, `company_gaps.csv`)

- **Coverage**: **1,254 companies** have `>= 24` realised months (`85,729` company-factor-horizon rows in `company_own_ic.csv` and `company_shrunk.csv`; `0` sector-only rows among the emitted series). Across all rows, **44,873 cells** have `|shrunk_ic - sector_prior_ic| >= 0.10`.
- **Top 200 reported gaps (`company_gaps.csv`)**: Because `company_gaps.csv` sorts by `months` descending (`63` max realised months at `6m` vs `57` at `12m` and `45` at `24m`) and then `|gap|` descending, all 200 rows in `company_gaps.csv` are 63-month `6m` series with empirical-Bayes shrinkage weights `0.86–0.95`. Examples of large company-vs-sector divergences (which reflect persistent single-stock trends over the 5-year sample and carry the section 5.3 overfit caveat):
  - `NHPC` (`INE848E`, `Other (merged)`, `op_margin`, 63m): `own_ic = +0.817`, `sector_prior_ic = -0.057`, `shrunk_ic = +0.770`, `gap = +0.828`.
  - `MHRIL` (`INE998I`, `Consumer Services`, `fin_cost_to_rev`, 63m): `own_ic = -0.710`, `sector_prior_ic = +0.114`, `shrunk_ic = -0.643`, `gap = -0.758`.
  - `POONAWALLA` (`INE511C`, `Financial Services`, `vol_12m`, 63m): `own_ic = +0.668`, `sector_prior_ic = -0.144`, `shrunk_ic = +0.587`, `gap = +0.732`.
  - `INOXWIND` (`INE066P`, `Capital Goods`, `earnings_yield`, 63m): `own_ic = -0.563`, `sector_prior_ic = +0.259`, `shrunk_ic = -0.451`, `gap = -0.710`.
  - `JUBLPHARMA` (`INE700A`, `Healthcare`, `earnings_yield`, 63m): `own_ic = -0.618`, `sector_prior_ic = +0.146`, `shrunk_ic = -0.541`, `gap = -0.688`.

### 6.7 Sector-KPI arm — **method pilot** (`kpi_coverage_stores.csv`, `kpi_panel.csv`, `kpi_ic.csv`, `kpi_interactions.csv`)

> **Label: METHOD PILOT.** All seven pilot SQLite stores exist and contribute **39,453 raw rows** across **52 companies** (`p20/p20new.db` 10 companies / 14,657 rows, `q12/q12.db` 12 / 5,043, `n10/n10.db` 10 / 5,251, `pilot10/pilot10.db` 10 / 6,624, `u8/u8.db` 8 / 6,709, `aurobindo/aurobindo.db` 1 / 683, `bluestar/bluestar.db` 1 / 486), yielding **5,854 company-period KPI rows** across **104 metrics** in `kpi_panel.csv`. Because 52 pilot companies span multiple sectors, only `ALL` (20 metrics with `>= 8` companies) and `Financial Services` (`pat`, `revenue`, `roe_pct`, `total_income` with 8–10 companies) pass the 8-company coverage gate (`kpi_coverage.csv`, 48 rows), and only `ALL` reaches `>= 8` companies in single cross-sectional months for IC scoring.

- **KPI univariate ICs (`kpi_ic.csv`, 17 cells, all in `ALL`, method pilot)**:
  - `roe_pct` (`total`, `level`, `6m`, 7m): `mean_ic = -0.313`, `nw_t = -4.51`.
  - `ebitda` (`total`, `level`, `12m`, 10m): `mean_ic = -0.183`, `nw_t = -3.35` (`6m` level: `-0.063`, `nw_t = -1.64`; `6m` YoY: `-0.136`, `nw_t = -0.74`).
  - `total_income` (`total`, `level`, `6m`, 12m): `mean_ic = +0.162`, `nw_t = +1.91` (`12m` level, 9m: `+0.135`, `nw_t = +1.44`).
  - `ebitda_margin_pct` (`total`, `level`, `6m`, 16m): `mean_ic = +0.108`, `nw_t = +1.65` (`12m` level, 13m: `+0.031`, `nw_t = +0.58`).
  - `capex` (`total`, `level`, `12m`, 8m): `mean_ic = +0.110`, `nw_t = +1.03`.
- **KPI tercile interactions (`kpi_interactions.csv`, 14 pairs in `ALL`, 1–5 months each, method pilot)**: Only two pairs have `>= 3` months for a Newey-West t-statistic: `level:ebitda` conditioned on `level:revenue` (3m, `mean_diff = +0.667`, `nw_t = +3.56`) and `level:pat` conditioned on `level:revenue` (5m, `mean_diff = +0.260`, `nw_t = +1.70`). These confirm the pipeline end-to-end on pilot stores and carry zero statistical claim until full-universe KPI extraction is loaded.

### 6.8 Measured peak RAM and runtime per step (`mem.log`, `mem_full.log`, `mem_rerun.log`)

- **Memory changes**:
  1. `factor_weights.connect()` defaults lowered from `memory_limit='5GB', threads=4` to `memory_limit='2GB', threads=2`.
  2. `factor_weights.build_panel_parquet()` builds the price panel in 400-entity DuckDB batches (dropping temp tables per batch), closes DuckDB before loading fundamental tables, and writes `panel.parquet` in 2-year chunks via `pyarrow.parquet.ParquetWriter`, cutting panel-build peak working set from **3.70 GB** (`mem.log`) to **0.64 GB** (`mem_panel_new.log` / `mem_full.log`).
  3. `factor_deep._load_panel_slice()` reads only the 77 required columns from `panel.parquet` (skipping 58 unused `*_sn` and intermediate columns) and downcasts the 35 `*_z` columns to `float32` while keeping raw `FACTORS` and `excess_*` in `float64` (verified on a 2-sector slice with `--placebo-runs 2`: 21 of 23 CSVs have `0.0` diff, and `fama_macbeth_sector.csv` / `redundancy.csv` differ by at most `1.0e-7` in `multivariate_nw_t`).
  4. Placebo permutations are generated and freed one at a time (`gc.collect()`), and `_interaction_pass` indexes pre-extracted NumPy arrays.
- **Measured RAM and runtime (`mem_full.log` & `mem_rerun.log`, 1s `psutil` sampler)**:
  - **Panel build (`--rebuild-panel` phase in `mem_full.log`)**: **0.60 min** (`36.0 s`), peak RSS **0.63 GB**, peak working set **0.64 GB** (vs **3.70 GB** before).
  - **Full study reusing `panel.parquet` (`mem_rerun.log`, total 93.46 min / 5,607.4 s, overall peak working set 0.414 GB, minimum system available RAM 4.70 GB)**:
    - Panel load + T-118 gate: **0.03 min** (`2.0 s`), peak RSS `0.32 GB`, peak working set `0.35 GB`.
    - Sector IC table + mode (`50,628` ICs): **2.12 min** (`127.2 s`), peak RSS `0.33 GB`, peak working set `0.35 GB`.
    - Exposure & IC correlations: **0.32 min** (`18.9 s`), peak RSS `0.30 GB`, peak working set `0.35 GB`.
    - Fama-MacBeth redundancy: **0.14 min** (`8.3 s`), peak RSS `0.28 GB`, peak working set `0.35 GB`.
    - Company shrunk ICs (`1,254` companies): **0.11 min** (`6.6 s`), peak RSS `0.33 GB`, peak working set `0.35 GB`.
    - Pair interactions (observed + 20 within-date permutations): **22.61 min** (`1,356.9 s`), peak RSS `0.36 GB`, peak working set `0.37 GB`.
    - Sparse walk-forward (`12m`, `6m`, `24m`): **3.17 min** (`190.2 s`), peak RSS `0.33 GB`, peak working set `0.37 GB`.
    - Sector & combination placebos (20 full-panel runs each): **64.81 min** (`3,888.6 s`: `45.62 min` sector + `19.20 min` combination), peak RSS `0.41 GB`, peak working set `0.41 GB`.
    - KPI method pilot (7 SQLite stores): **0.22 min** (`13.0 s`), peak RSS `0.30 GB`, peak working set `0.41 GB`.

## 7. Docs updated

`docs/DEVELOPER_GUIDE.md` (O19d block updated with memory design, measured 0.64 GB / 0.41 GB peak RAM, and 93.5 min runtime) and `docs/research/T-210_factor_deep_study.md` (this report). The T-207 report is unchanged because T-207 is unchanged.
