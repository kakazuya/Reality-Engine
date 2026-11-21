# T-229: a point-in-time factor panel from the 91 Telegram stores

Ticket T-229 (Shivam, 21 Nov 2026).  The universe factor study
(T-118/T-207/T-210, `docs/research/T-210_factor_deep_study.md`) ran on the XBRL truth snapshot.
Stage A rebuilds the same monthly factor panel from the 91 company stores we built properly
(`D:/RealityEngine/tg_build/measure10/cNN/cNN.db`), point in time, and validates it against the
T-207 panel; stage B measures factor ICs on it, controls the Nov-2026 selection and adds the
T-228 claim factors; stage C (§10) quantifies the widened text claims and the deck observations
and tests them over the hard numbers.  **Every stage-B/C number is conditional on "91 companies
picked in Nov 2026"; nothing here is a universe claim.**

Code `reality_engine/research/factor_store91.py` (+ `factor_store91_stageb.py` for stage B,
`factor_store91_stagec.py` for stage C), tests `reality_engine/tests/test_factor_store91.py`
(6 synthetic tests), `test_factor_store91_stageb.py` (4) and `test_factor_store91_stagec.py`
(6), output `.tmp/t229/`.

```bash
python -m pytest -q reality_engine/tests/test_factor_store91.py reality_engine/tests/test_factor_store91_stageb.py  # 10 passed
python -m pytest -q reality_engine/tests/test_factor_store91_stagec.py    # 6 passed
python -m reality_engine.research.factor_store91 --out .tmp/t229          # stage A: panel + validation + coverage
python -m reality_engine.research.factor_store91_stageb --out .tmp/t229   # stage B: targets, ICs, control, placebo, claims
python -m reality_engine.research.factor_store91_stagec --out .tmp/t229   # stage C: text/deck coverage (+ ICs when the gate passes)
```

The stores, the truth snapshot (`truth_2026-11-04.duckdb`) and the T-228 claims database are
opened read-only; the only writes are under `--out`.  No model call was made.

## 1. Data and panel

| item | value |
|---|---|
| stores read | 91 `cNN/cNN.db` (the `c40_crash_*` copy is skipped; `_ocr`/`pages` files are not stores) |
| trading calendar | union of NSE `price_delivery` dates, 1,944 sessions `2019-01-01`..`2026-11-09` |
| rebalance dates | last session of each month, 30 from `2024-06-28` to `2026-11-09` (the 2026-11 partition ends at the data end, so its "month-end" is 09 Nov) |
| panel | 2,730 rows = 91 companies x 30 month-ends, 45 columns |
| rows missing `known_at` | 0 of 95,056 fin/shareholding/guidance/KPI rows read (stop rule: < 5%) |
| reporting basis chosen | 53 stores standalone, 35 consolidated, 3 stores with no quarterly financials (`c41`, `c51`, `c77`; 90 blank rows) |
| targets | 2,266 3m, 1,994 6m, 1,453 12m realised; month-ends with >= 20 names and a realised 6m target: **23** (stop rule: >= 15) |
| truth link | 87 of 91 stores and 2,610 of 2,730 rows linked by ISIN (symbol fallback); the rest are outside the T-207 universe filter or absent from the snapshot |

Returns use `price_delivery.adj_close` (the split/dividend-adjusted series; a raw close would
turn every split into a fake -50%).  Excess return = the raw forward return minus the equal-weight
mean of that month's 91 names; a company with no price on the horizon session gets NaN, never a
stale fill.

## 2. Factors (definitions fixed before any result)

Same names and definitions as T-207 (`reality_engine/research/factor_weights.py`) wherever one
exists; the last eight are store-only.

| factor | definition | T-207 counterpart |
|---|---|---|
| `q_rev_yoy` | latest quarter revenue / same fiscal quarter a year earlier - 1 | none (new) |
| `q_pat_yoy` | same for PAT; only when current PAT > 0 (T-207 guard) | yes |
| `ttm_rev_yoy` | TTM revenue / prior TTM - 1, four consecutive quarters each (span 250-290 d), base matched by fiscal quarter 330-400 d back | yes |
| `ttm_pat_yoy` | same for PAT | yes |
| `op_margin` | TTM operating profit / revenue; operating profit = revenue - (`total_expenses` - `finance_cost` - `depreciation`), T-207's formula | yes |
| `op_margin_chg` | current TTM operating margin - year-ago TTM operating margin | yes |
| `earnings_yield` | TTM PAT / market cap | yes |
| `sales_yield` | TTM revenue / market cap | yes |
| `fin_cost_to_rev` | TTM finance cost / TTM revenue | yes |
| `net_debt_chg_4q` | (`net_debt` - `net_debt` 12 month-ends earlier) / TTM revenue, gap 330-400 d | none (new) |
| `promoter_chg_1q`, `promoter_chg_4q` | promoter % minus the previous / fourth-previous available quarter (percentage points), T-207's shift rule | yes |
| `fpi_chg_4q`, `mf_chg_4q` | `fpi_total` / `mutual_funds` % change over four quarters | none (new) |
| `pledge_pct` | latest printed pledged % of promoter holding; 0 when the filing says no pledge, NaN when no filing | none (new) |
| `delivery_3m` | mean `delivery_pct` over the prior 63 sessions | yes |
| `mom_12_1` | `adj_close[t-21] / adj_close[t-252] - 1` | yes |
| `vol_12m` | sample std of the prior 252 daily log returns | yes |
| `size` | log market cap on the rebalance date | yes |
| `guidance_rev` | latest revenue-growth guidance: midpoint raised vs its `revision_of` row = +1, cut = -1, no revision / no row = 0 / NaN | none (new) |
| `guidance_growth` | latest guided revenue-growth midpoint (fraction) - trailing `ttm_rev_yoy` | none (new) |
| `order_cover` | latest stated `order_book` / TTM revenue (`kpi_series`) | none (new) |

Financials: the three margin factors are set NaN for companies the truth snapshot labels
`Financial*`, exactly T-207's mask; the label is today's, T-207's own caveat, and 120 panel rows
were masked.  A store's reporting basis is chosen once per company (consolidated when the two
bases have at least as many current preferred rows, else standalone) and never mixed.

## 3. Point-in-time rule

1. **Quarterly figures.** The candidate set is the rows the store's own election typed with a
   `preferred_from` window (`fin_quarter_xbrl` + `fin_quarter_printed`, the T-090 election).  A
   row's availability session comes from its `known_at` through `factor_weights.pit_sessions`: a
   filing after 15:30 IST counts from the next session.  At a rebalance date the figure of each
   (`fiscal_period`, `line_item`) is the candidate with the newest availability session on or
   before that date; `preferred_to` hands the key to the next row on the session its filing became
   usable, so a restatement filed after the close cannot leak into that close.
2. **Quarter grid.** Reported Q rows; a missing quarter is derived from the store's own cumulative
   columns (Q2 = H1 - Q1, Q3 = 9M - H1, Q4 = FY - 9M), the same fallback T-207 applies to XBRL
   filings.  A TTM needs four consecutive quarters (250-290 d); its year-ago base is matched by
   fiscal quarter (330-400 d), not by row position, so a quarter that prints only as an annual
   column leaves the YoY blank instead of comparing the wrong year.
3. **Shareholding / pledge / guidance / KPI** rows use the same `known_at` -> session rule; a
   revised SHP quarter replaces its original from the revision's session, not before.
4. **Price / valuation** rows describe their own session (`known_at` is the trading date), so they
   are used on that date.

## 4. Validation against the T-207 panel

The T-207 panel was rebuilt with `factor_weights.build_panel_parquet` on the read-only truth
snapshot for `2024-06-01`..`2026-11-04` (41,700 rows, 2,052 companies, 30 month-ends), then
joined to the store panel on date + linked ISIN.  Per factor: overlap, Spearman rho, share of pairs
within 5% relative, median relative difference.  The 10 worst pairs per factor (both values and the
store row's source) are in `validation_worst.csv`.

| factor | overlap | Spearman rho | within 5% | median rel. diff |
|---|---:|---:|---:|---:|
| q_pat_yoy | 1,090 | 0.913 | 67.3% | 0 |
| ttm_rev_yoy | 770 | 0.939 | 66.5% | 0 |
| ttm_pat_yoy | 636 | 0.963 | 63.8% | 5.3e-7 |
| op_margin | 996 | 0.832 | 75.4% | 0 |
| op_margin_chg | 664 | 0.835 | 63.4% | 8.8e-7 |
| earnings_yield | 1,029 | 0.855 | 66.5% | 2.0e-4 |
| sales_yield | 1,097 | 0.945 | 71.0% | 1.1e-4 |
| fin_cost_to_rev | 1,011 | 0.855 | 77.6% | 0 |
| promoter_chg_1q | 1,316 | 0.961 | 23.8% | 0 |
| promoter_chg_4q | 1,296 | 0.972 | 52.0% | 0 |
| delivery_3m | 1,555 | 1.0000 | 99.5% | 1.2e-16 |
| mom_12_1 | 1,563 | 0.993 | 97.8% | 0 |
| vol_12m | 1,563 | 0.996 | 98.3% | 1.8e-3 |
| size | 1,461 | 0.971 | 99.1% | 2.3e-7 |

`q_rev_yoy`, `net_debt_chg_4q`, `fpi_chg_4q`, `mf_chg_4q`, `pledge_pct`, `guidance_rev`,
`guidance_growth` and `order_cover` have no T-207 counterpart (`q_rev_yoy` is absent from
`factor_weights.FACTORS`; the others need the stores' ownership / guidance / order rows), so they
are not validated here.

**Reading the table.** Price, delivery, momentum and size reproduce almost exactly (rho >= 0.97,
98-100% within 5%), which validates the calendar, the adjustment choice and the PIT session rule.
Ownership levels reproduce strongly by rank (rho 0.96-0.97) but the *change* factors have a thick
tail: most pairs are exactly equal (median diff 0), and the share within 5% is dragged down by
near-zero changes where a 0.01 pp rounding difference is a 100% relative move.  Fundamentals agree
by rank (rho 0.83-0.96) with 64-78% within 5%; the tail is dominated by the reporting basis
difference below.

Worst disagreements (`validation_worst.csv`), all with the store row source:

| factor | date | company | store | panel | source |
|---|---|---|---|---|---|
| fin_cost_to_rev | 2026-03-30 | GREENPOWER | 0.207 | 5.2e-8 | `fin_quarter_xbrl` Q3FY26, known 2026-02-04 |
| earnings_yield | 2025-05-30 | JGCHEM | 0.0136 | 4.5e-7 | `fin_quarter_xbrl` Q4FY25, known 2025-05-19 |
| op_margin | 2025-01-31 | GREENPOWER | 0.652 | 0.0140 | `fin_quarter_xbrl` Q3FY25, known 2025-01-24 |
| q_pat_yoy | 2025-05-30 | GANECOS | -0.299 | 0.0013 | `fin_quarter_xbrl` Q4FY25, known 2025-05-24 |
| ttm_rev_yoy | 2025-02-28 | BLKASHYAP | 0.298 | 0.0106 | `fin_quarter_xbrl` Q3FY25, known 2025-02-07 |
| promoter_chg_1q | 2025-08-29 | GANECOS | 3.19 | 0.28 | `shp_category` SHP_1508713, known 2025-08-11 |
| vol_12m | 2025-10-31 | ABINFRA | 0.106 | 0.036 | `price_delivery` NSE 2025-10-31 |

Root causes checked: GREENPOWER is the basis rule (the store picks consolidated because both bases
have 10 recent quarters; the truth panel's all-history count picked standalone, whose finance cost
is zero, hence the 4e6 relative gap).  GANECOS' promoter row is a quarter-alignment/coverage
difference between `shp_category` and the snapshot's `shp_index`, not a wrong value.  The ABINFRA
volatility gap is the price series, not the formula: that store holds 1,095 NSE rows over
2019-2026 (sparse sessions) and its `adj_factor` prints 0.2/0.1 in April 2025 before jumping to
1.0, so its adjusted series carries jumps the truth panel's series does not.

## 5. Coverage

`coverage_factor.csv`: companies with a non-null value per month-end, and
`coverage_month.csv`: realised targets per month.

| factor | months with a value | min / median / max names | total values |
|---|---:|---:|---:|
| q_rev_yoy | 30 | 55 / 79 / 87 | 2,260 |
| q_pat_yoy | 30 | 46 / 65 / 86 | 1,990 |
| ttm_rev_yoy | 26 | 1 / 62 / 80 | 1,426 |
| ttm_pat_yoy | 23 | 8 / 58 / 74 | 1,240 |
| op_margin | 28 | 1 / 71 / 78 | 1,763 |
| op_margin_chg | 26 | 1 / 56 / 73 | 1,231 |
| earnings_yield | 28 | 1 / 72 / 82 | 1,818 |
| sales_yield | 28 | 1 / 73 / 81 | 1,835 |
| fin_cost_to_rev | 28 | 1 / 71 / 80 | 1,800 |
| net_debt_chg_4q | 18 | 63 / 67 / 71 | 1,202 |
| promoter_chg_1q | 30 | 75 / 80 / 82 | 2,373 |
| promoter_chg_4q | 30 | 71 / 77 / 82 | 2,298 |
| fpi_chg_4q | 25 | 1 / 74 / 80 | 1,339 |
| mf_chg_4q | 25 | 1 / 59 / 65 | 1,090 |
| pledge_pct | 30 | 4 / 80 / 82 | 2,281 |
| delivery_3m | 30 | 76 / 87 / 90 | 2,554 |
| mom_12_1 / vol_12m | 30 | 75 / 83 / 91 | 2,495 each |
| size | 30 | 71 / 80 / 82 | 2,365 |
| guidance_rev | 30 | 14 / 37 / 47 | 1,085 |
| guidance_growth | 26 | 1 / 26 / 36 | 594 |
| order_cover | 26 | 1 / 6 / 8 | 159 |

Targets per month: 80-91 names for 3m and 6m, 80-90 for 12m while its window is closed
(2024-06-28..2025-10-31).  The panel's first months are fundamental-thin by construction: a
four-quarter TTM needs four known quarters and the stores hold comparatives from 2024 filings, so
`ttm_rev_yoy` starts with 1 name at 2024-06-28 and reaches 62 median from November 2024;
`net_debt_chg_4q` needs twelve month-ends and starts 2025-06.

## 6. Stop rules

- `known_at` present on every row read (0 of 95,056 missing) -> the 5% rule does not trigger.
- 23 month-ends have >= 20 names with a realised 6m target (the rule needs >= 15) -> the study does
  not stop.

## 7. Limits carried into stage B

- **Selection bias.** The 91 stores were picked in Nov 2026 on recent results strength
  (`build_queue.csv`: `pead_score`, `fwd_pe`, `order_win_60d`).  Every result on them is
  conditional on that selection; stage B's control set is what measures it, and nothing here does.
- **Reporting basis.** The store picks consolidated on a tie (it only holds recent quarters); the
  truth panel's all-history count sometimes picked standalone.  This is the main reason a
  fundamental pair can disagree while its rank relation holds, and it is a deliberate store-side
  choice (group accounts), not a data error.
- **"Within 5% relative" is harsh near zero.** For growth and percentage-point-change factors a
  near-zero denominator turns a rounding difference into a large relative gap.  Report rho and the
  median relative difference beside it; the CSV has all three.
- **The last rebalance is a partial month.** 2026-11-09 is the data end, not a month-end; it is kept
  so the panel ends on the last session, as T-207's builder does.
- **Sector mask is today's label.** Financial margins are nulled from the truth snapshot's
  `company_industry`, and only for linked names (120 rows).
- **Sparse store-only factors.** `order_cover` comes from 8 stores and `guidance_growth` from the
  53 stores that state a revenue-growth target; they are panel-ready but thin.
- **No return claim.** Stage A has no IC, no ranking and no forward-return result; the `excess_*`
  columns are targets only.
- Peak memory stays under 0.5 GB (95k store rows + a column-pruned 41.7k-row truth panel); the
  truth panel build is the slow step (~8 min under the concurrent CPU load, reused on reruns).

## 8. Stage B: ICs, selection control, placebo and T-228 claims

**Label: 91 companies picked in Nov 2026.**  Full tables: `D:/RealityEngine/t229/stage_b.md` (copied from `.tmp/t229/` by Wolf, 21 Nov); machine-readable
outputs `target_check.csv`, `target_check_flagged.csv`, `ic_side_by_side.csv`, `control.csv`,
`placebo.csv`, `power.csv`, `claims_coverage.csv`.  Code
`reality_engine/research/factor_store91_stageb.py`, tests 4 synthetic (BH, placebo, matched draw,
claim PIT), all passing.

### 8.1 Targets: truth prices, store prices as a check

Forward 3/6/12-month returns were rebuilt from the read-only snapshot as T-207 does: NSE row first,
``tr_close`` forward over the shared NSE session index, minus the NIFTY 500 TRI return; 3m is new.
The query reads only the ~120 price dates the rebalances and horizons can touch (267,431
company-date-horizon rows).  The store targets stay only as a check:

| horizon | pairs | raw rho pooled | raw rho monthly median | excess pooled | excess monthly median | companies > 5pp | mean abs diff |
|---|---:|---:|---:|---:|---:|---:|---:|
| 3m | 2,146 | 0.9978 | 0.9997 | 0.7770 | 0.9997 | 1 | 0.0026 |
| 6m | 1,877 | 0.9963 | 0.9995 | 0.7478 | 0.9995 | 2 | 0.0059 |
| 12m | 1,342 | 0.9905 | 0.9895 | 0.8585 | 0.9895 | 2 | 0.0166 |

The overall raw-return rho is **0.9948** (stop rule < 0.90 not triggered).  The excess-vs-excess
rho is lower only because the store excess is relative to the equal-weight mean of the 91 and the
truth excess is relative to NIFTY 500: the wedge is one number per month, so within-month ranks are
identical (monthly median 0.99) and cross-sectional ICs cannot see it.  The two > 5pp companies are
a store `adj_factor` break, not a truth-side issue: **CNCRD** (c82, 12m mean 0.705, max 1.202) and
**VIVIANA** (c12, 12m mean 0.330, max 0.592); they keep truth targets, so the break cannot move a
return.

The four stores outside the T-207 panel (`PANCHMAHQ`, `RAJRILTD`, `BIL`, `HYPERSOFT`) are present in
the snapshot's ``px_daily`` (they failed the panel's liquidity/history filter, not the price store),
so truth targets were computed for **all 91**; none of the four is flagged.  This replaces the
brief's "87 + 4 store-price fallback" split and removes the need to drop any of the four.

### 8.2 ICs, store values against the truth panel's values

Monthly Spearman across companies (>= 20 names), Newey-West t with lags = horizon months - 1
(2/5/11), both runs on the same pairwise-complete company-months.  The store side has 23 factors
(22 store + `claim_count_12m` through the gate), the truth side 14.  Store-side cells with
|t| >= 2 and their truth counterpart:

| factor | h | months | mean IC | NW t | sign share | truth mean IC | truth t |
|---|---|---:|---:|---:|---:|---:|---:|
| promoter_chg_4q | 12m | 16 | 0.1853 | 6.79 | 1.00 | 0.1855 | 7.58 |
| sales_yield | 6m | 17 | 0.2443 | 5.66 | 1.00 | 0.2741 | 3.65 |
| earnings_yield | 6m | 17 | 0.1581 | 5.47 | 0.94 | 0.1854 | 4.24 |
| delivery_3m | 6m | 22 | 0.1079 | 5.45 | 0.77 | 0.1080 | 5.47 |
| q_pat_yoy | 12m | 16 | 0.0953 | 4.83 | 0.94 | 0.1182 | 5.07 |
| delivery_3m | 12m | 16 | 0.1864 | 4.64 | 0.94 | 0.1866 | 4.64 |
| size | 3m | 25 | -0.1399 | -4.34 | 0.88 | -0.1432 | -3.69 |
| sales_yield | 3m | 20 | 0.1414 | 4.06 | 0.80 | 0.1647 | 3.16 |
| size | 6m | 22 | -0.1724 | -3.91 | 0.86 | -0.1706 | -3.47 |
| size | 12m | 16 | -0.2586 | -3.21 | 1.00 | -0.2483 | -3.55 |
| claim_count_12m | 6m | 22 | 0.0848 | 2.54 | 0.73 | - | - |
| earnings_yield | 3m | 20 | 0.1147 | 2.54 | 0.70 | 0.1477 | 3.18 |
| promoter_chg_4q | 6m | 22 | 0.1281 | 2.26 | 0.77 | 0.1357 | 2.17 |
| q_rev_yoy | 6m | 22 | 0.0932 | 2.14 | 0.82 | - | - |

Store and truth values move together (stage A: rho 0.83-0.97 per factor).  The store side shows
fewer months for fundamental factors because the same-company-months rule keeps only rows where the
truth-side value also exists.  Three cells have a **sign difference**: `ttm_rev_yoy` 12m (store
+0.065 vs truth -0.008) and `fin_cost_to_rev` 6m and 12m (store -0.044/-0.045 vs truth
+0.015/+0.025); all other overlapping factors share the sign.  The full 111-row side-by-side is in
`stage_b.md` / `ic_side_by_side.csv`.

### 8.3 Selection control: 50 seeded draws of 91 matched companies

Draws from the truth panel excluding the 91, matched on today's sector and size tercile, seed 229,
50 draws; every sector x size cell had enough names (0 fallbacks).  For every factor x horizon the
control recomputes the truth-side IC on the drawn 91 and locates our 91's IC in that distribution
(42 cells):

| cell | our mean IC | draw median | percentile |
|---|---:|---:|---:|
| size 3m | -0.1432 | 0.0819 | 0 |
| size 6m | -0.1706 | 0.0996 | 0 |
| size 12m | -0.2483 | 0.1481 | 0 |
| op_margin 6m | -0.0544 | 0.0705 | 2 |
| ttm_pat_yoy 3m | -0.0740 | 0.0023 | 4 |
| sales_yield 3m / 6m / 12m | 0.1647 / 0.2741 / 0.3718 | -0.0301 / -0.0565 / -0.0512 | 100 / 100 / 100 |
| q_pat_yoy 12m | 0.1182 | -0.0047 | 100 |
| earnings_yield 3m / 6m / 12m | 0.1477 / 0.1854 / 0.2675 | 0.0068 / 0.0110 / 0.0315 | 98 / 96 / 98 |
| delivery_3m 12m | 0.1866 | 0.0177 | 98 |
| promoter_chg_4q 12m | 0.1855 | 0.0414 | 96 |
| vol_12m 6m | -0.0175 | -0.1208 | 96 |

Five of 42 cells sit at or below the 5th percentile and 12 at or above the 95th.  The selection is
most visible in **size**: the 91 are not a random small-cap sample, and within their matched size
buckets the usual size premium is inverted (percentile 0 at every horizon).  Valuation and delivery
are at the opposite end: the 91's own ICs sit far above what matched companies would give, which is
the cost of reading any of these ICs as a universe result.

### 8.4 Placebo and power

200 within-date permutations of the target on the same pairwise-complete company-months (seed 229);
two-sided p = (1 + #(|null mean IC| >= |observed|)) / 201; Benjamini-Hochberg 10% over the 48 cells
with >= 12 months.  **17 cells survive BH**: `size` 3m/6m/12m; `sales_yield` 3m/6m; `earnings_yield`
3m/6m; `delivery_3m` 6m/12m; `promoter_chg_4q` 6m/12m; `q_rev_yoy` 3m/6m; `pledge_pct` 3m/6m;
`claim_count_12m` 6m/12m.  The 200-permutation floor is p = 0.004975; that is the p of most
survivors, so the ranking among them is not resolvable at this draw count.

Power (80%, two-sided 5%, non-overlapping windows = months / horizon length): **6m** 22 months,
3.67 effective windows, median monthly-IC sd 0.098 -> smallest detectable mean IC **0.143**;
**12m** 16 months, 1.33 windows, sd 0.121 -> **0.294**.  A 12m mean IC below ~0.29 is not
detectable here at 80% power; the 12m survivors (size -0.259, sales 0.372, promoter 0.185, delivery
0.186, q_pat 0.118) sit at or above that edge.

### 8.5 T-228 text claims (final database)

Source `D:/RealityEngine/t228/claims_91.db` (final: 1,159 verified, 2,901 unverified, 10
quarantined; 52 symbols).  It is read through a byte copy under `--out` because the source
directory cannot create SQLite WAL side files from this worktree.  Only `status='verified'`, only
claims available by the month-end (same 15:30 IST rule), and only these four factors:
`claim_rev_growth` (latest `revenue.total`, unit pct, midpoint minus `ttm_rev_yoy`; the new
`revenue.mix` node is not growth and is excluded by the `revenue.total` filter), `claim_margin_dir`
(sign of the latest `margin.*` claim), `claim_debt_dir` (sign of the latest `debt.level` change),
`claim_count_12m` (verified claims in the trailing 12 months).

| factor | companies | months with value | months >= 20 names | median / max names | gate |
|---|---:|---:|---:|---:|---|
| claim_rev_growth | 27 | 26 | 11 | 17.5 / 27 | fail (11 < 12) |
| claim_margin_dir | 30 | 30 | 16 | 20 / 30 | fail per horizon (11 / 8 / 2) |
| claim_debt_dir | 8 | 30 | 0 | 5 / 8 | fail |
| claim_count_12m | 52 | 30 | 30 | 41 / 52 | pass (25 / 22 / 16 months at 3/6/12m) |

Only `claim_count_12m` gets an IC: 3m 0.0207 (t 0.64), 6m 0.0848 (t 2.54), 12m 0.1138 (t 1.67);
placebo p 0.572 / 0.0348 / 0.0149, surviving BH at 6m and 12m.  `claim_rev_growth` misses the gate by
one month because the factor also needs the store's TTM revenue (the early months are TTM-thin);
it is coverage only.  `claim_margin_dir` has 16 months with >= 20 names before a horizon is
required, but only 11 / 8 / 2 months remain once the target window has closed.

### 8.6 Limits of stage B

- Every number is conditional on **91 companies picked in Nov 2026**.  The control measures the
  selection only inside the truth panel's own liquidity-filtered universe, so it is a matched
  benchmark, not the population of Indian small caps.
- Overlapping windows: NW t with h-1 lags is still optimistic; the 12m series has 16 months, about
  1.3 independent windows, which is why its power floor is 0.29.
- The placebo has 200 permutations (minimum p 0.005) and BH 10% is lenient under overlap; the
  surviving set is evidence of rank stability, not of a tradable return.
- No transaction costs, no shorting, no portfolio construction and no claim that the 91 are
  investable; the `excess_*` columns are measurement targets.
- Text-claim factors are thin and the T-228 database is still growing (the counts above are the
  final 21 Nov read); only one of the four passes the coverage gate.

## 9. Docs updated

`docs/research/T-229_factor_store91.md` (this report, stages A, B and C).  No other documentation
file was changed by this ticket; `tasks/STATE.md` is Wolf's.

## 10. Stage C: text and deck factors, and what they add to the hard numbers

Plan step 2 (Shivam, 21 Nov 2026): text-derived facts must be quantified onto revenue, cost, debt
or capital, then tested for prediction **over** the hard numbers (6m/12m).  Two evidence sources
are new since stage B: T-228 driver claims widened to annual reports, press releases and
announcements, and T-230 deck observations stored with meaning.  Code
`reality_engine/research/factor_store91_stagec.py`, tests
`reality_engine/tests/test_factor_store91_stagec.py` (6 synthetic), machine-readable outputs
`coverage_c.csv`, `ic_c.csv`, `placebo_c.csv`, `power_c.csv`, `incremental_c.csv`,
`deck_agreement.csv` and full tables `stage_c.md` under `.tmp/t229/`.

```bash
python -m pytest -q reality_engine/tests/test_factor_store91_stagec.py   # 6 passed
python -m reality_engine.research.factor_store91_stagec --out .tmp/t229  # claims_91 + obs_91
python -m reality_engine.research.factor_store91_stagec --out .tmp/t229 \
    --claims D:/RealityEngine/t228/claims_91_s2.db                       # stage-2 widened claims
```

The panel (`D:/RealityEngine/t229/panel.parquet`, stage A), the truth snapshot targets and the IC
arithmetic are stage B's; no stage-A/B output is changed.  Both evidence databases are opened
through a byte copy under `--out` (WAL side files cannot be created on the source drive).

### 10.1 Factors (definitions written before any IC was computed)

| factor | definition | source |
|---|---|---|
| `claim_order_inflow_12m` | sum of **distinct order wins** announced in the trailing 365 days (midpoint of the printed range, crore) / store TTM revenue; a repeat announcement of the same order counts once | T-228 claims |
| `claim_capex_12m` | latest verified `capex.amount` known by the month-end per (symbol, segment, effective_period), summed across the distinct keys in the trailing 365 days (midpoint, crore) / market cap | T-228 claims |
| `claim_dilution_12m` | sum of verified `equity.shares` money raises (QIP, warrants, preferential, rights; crore) announced in the trailing 365 days / market cap | T-228 claims |
| `claim_rev_growth` | stage-B definition: latest `revenue.total` pct claim midpoint / 100 minus the store's `ttm_rev_yoy` | T-228 claims |
| `claim_count_12m` | stage-B definition: verified claims usable in the trailing 365 days | T-228 claims |
| `deck_order_cover` | latest verified company-scope deck `order.book` (value x the stored scale, crore) / store TTM revenue | T-230 observations |
| `deck_capacity_growth` | latest verified company-scope `capacity.add` / the latest `capacity.total` with the **same normalised unit and segment**; no same-key total means NaN, never a cross-unit ratio | T-230 observations |

**Order wins are flows, a deck order book is a stock: they are never added.**  A T-228
`revenue.order_book` claim is an order win only when its source is an announcement or press
release (the driver tree stores a won order and a stated order-book level under the same node);
transcript and guidance order-book levels and targets are excluded.  The stage-2 `speaker_scope`
must be `company` and the stage-2 `dup_of` losers are dropped when those columns exist.  For the
sums, rows with the same symbol, availability session and printed value are counted once (the
same fact re-filed twice); `claim_count_12m` keeps stage B's row count.

**Restatements and repeat announcements.**  Capex is elected per (symbol, segment,
effective_period): the newest claim known by the month-end replaces earlier values for the same
plan, and the factor sums the surviving distinct keys in the window -- ALICON's FY26 Rs 125-130
crore appears in three claims and counts once at Rs 127.5 crore.  Period keys are case- and
punctuation-folded (`FY26` = `FY '26`); a blank period is its own key.  An order win announced
twice is collapsed only when the two rows are at most 30 days apart, their crore values are within
1%, and the statement/quote/context texts share at least two non-boilerplate tokens (the
customer/description signal); filing boilerplate alone cannot collapse two different orders.  The
earliest announcement of the pair is kept.

**Unit handling.**  Claim amounts are converted only from `inr_cr`, `inr_lakh`, `inr_mn` and
`inr_bn`; any other printed unit (`usd_mn`, `pct`, `tons`, ...) is skipped and counted, never
treated as rupees.  Deck money rows are scaled by the observation's stored `scale` (so
`INR Mn` x 1e6 and `Rs Cr` x 1e7 both become rupees).  Capacity growth divides
`value x scale` by `value x scale` for the same unit key; a unit that has no same-key total is
skipped and counted.

**Deck filters.**  `status='verified'`, `entity_scope='company'`, never `adjusted=1`, never
`series_kind='bridge'`.  At the latest availability the empty-segment order-book row (the printed
total) is preferred, else the largest printed value.  For `capacity.add`, a blank stage counts
(the store leaves it unlabelled in most decks) together with `operating`, `under_construction`
and `approved`; `under_review` and `potential` pipeline rows are excluded as speculative.

### 10.2 Point in time and the gate

A claim or observation's availability session is its `known_at` through
`factor_weights.pit_sessions`: at or before 15:30 IST on a trading day it counts from that session,
otherwise the next one; a date-only `known_at` means midnight.  A month-end sees only rows whose
availability session is at or before it; trailing-12-month sums use the same availability session.
`known_at` is present on **0 of 1,159 verified claims (claims_91; 4,070 rows in the table)** and
**0 of 102,398 observations**, so the brief's 5% stop rule does not trigger.  Claims filed after
the panel's last session (2026-11-09) get no availability session and are dropped: 84 of the
1,159, leaving **1,075 usable verified claims**.

The coverage gate is stage B's: a factor passes when at least one horizon has >= 12 month-ends
carrying >= 20 names **and** a realised target.  A failed gate is a result and is reported, not
tuned away.

### 10.3 Incremental test

Each passing factor is residualised cross-sectionally at every month-end by OLS on the six stage-B
survivors -- `sales_yield`, `earnings_yield`, `promoter_chg_4q`, `delivery_3m`, `q_pat_yoy`,
`size`.  The factor and every control are rank-standardised across that month's names first (so a
fat-tailed ratio cannot set the slope and the residual is scored on the same rank scale as the
Spearman IC); a month needs at least controls + 3 names.  Raw IC and residual IC are computed on
the same pairwise-complete company-months, with Newey-West t (lags = horizon months - 1) and the
stage-B placebo (200 within-date target permutations, seed 229).  The matched random control of
stage B **cannot be computed for these factors**: claims and deck observations exist only for the
91, so a matched draw has no text/deck value to measure.  The selection control therefore carries
over from stage B unchanged; every stage-C number remains conditional on "91 companies picked in
Nov 2026".

### 10.4 Results on the stage-1 claims database

Run 21 Nov 2026: `claims_91.db` (1,159 verified, 1,075 usable) and `obs_91.db` (860 usable verified
company-scope rows).  Coverage, per the gate of §10.2 (`months_ge20_<h>` counts month-ends with
>= 20 names **and** a realised h-month target):

| factor | companies | months with value | months >= 20 names | median / max names | 3m / 6m / 12m | gate |
|---|---:|---:|---:|---:|---:|---|
| `claim_order_inflow_12m` | 0 | 0 | 0 | 0 / 0 | 0 / 0 / 0 | fail |
| `claim_capex_12m` | 28 | 30 | 7 | 14 / 24 | 2 / 0 / 0 | fail |
| `claim_dilution_12m` | 2 | 25 | 0 | 1 / 1 | 0 / 0 / 0 | fail |
| `claim_rev_growth` | 27 | 26 | 11 | 17.5 / 27 | 6 / 3 / 0 | fail |
| `claim_count_12m` | 52 | 30 | 30 | 41 / 52 | 25 / 22 / 16 | **pass** |
| `deck_order_cover` | 11 | 25 | 0 | 7 / 11 | 0 / 0 / 0 | fail |
| `deck_capacity_growth` | 8 | 30 | 0 | 3 / 8 | 0 / 0 / 0 | fail |

**Only `claim_count_12m` passes, so the brief's stop rule fires (fewer than 2 factors): coverage
is reported and no stage-C IC, placebo, power or incremental table is computed on `claims_91`.**  
This is a coverage result, not a null result:

- **Order inflow is empty by construction.**  `claims_91.db` is stage 1 (transcripts and guidance):
  all 60 verified `revenue.order_book` claims are order-book *levels* or targets, and a factor that
  sums order wins correctly excludes them.  The first statement it can see is the widened
  announcement/AR/press-release database.
- **Capex reaches a 20-name cross-section only at the very end.**  28 companies have an announced
  capex, but the 20-name months run from 2026-05 onward, where only 2 month-ends still have a
  realised 3m target and none has 6m or 12m.
- **Revenue-growth guidance misses the per-horizon gate.**  11 month-ends have >= 20 names before
  a target is required (stage B measured the same 11 against its 12), and the late clustering of
  claim coverage leaves 6 / 3 / 0 after the 3m / 6m / 12m window closes.
- **Dilution is 2 companies** (ESTER, SPMLINFRA); the other `equity.shares` rows are stake
  percentages or acquisition-stake sizes, correctly not money raised.
- **The two deck factors cannot form 20-name cross-sections on the 91.**  14 companies hold a
  verified company-scope order book and 11 of those also have a store TTM revenue; 13 companies
  hold a capacity add, and only 8 ever meet a same-unit total (11 hit a month-end with no
  same-unit total at all).  The deck order-book definition was
  checked against the store KPI `order_cover` anyway: **68 pairs on 4 companies, pooled Spearman
  0.423, 48.5% within 10%** (no month has 3 such pairs, so no monthly median).  The two sources
  disagree on level often enough that `deck_order_cover` should be treated as a different measure
  from `order_cover`, not a second print of it.

**Stage-2a pilot (schema smoke check):** `D:/RealityEngine/t228/s2a/claims_s2_pilot.db` (290
verified, 289 usable; `source_kind` present, `speaker_scope`/`dup_of` absent) runs the same command
and puts `claim_order_inflow_12m` on **2 companies / 25 months** (the announcement order wins of
BLKASHYAP and JYOTISTRUC), `claim_capex_12m` on 4, `claim_rev_growth` on 3 and `claim_count_12m`
on 11.  The source split works; 12 stores cannot form a 20-name cross-section, which is the
expected pilot result, not a code failure.  The repeat rule is visible on the pilot: JYOTISTRUC's
order-win rows sum to Rs 8,810.34 crore but Rs 7,471.50 crore once each order counts once (the
689.93 and 648.91 repeats collapse), while BLKASHYAP's 18 different orders stay at Rs 6,263.98
crore; MICEL's announcement rows print `inr` (rupees) and are skipped by the unit rule.

**Next step (waits for Wolf).**  The same command on the widened
`--claims D:/RealityEngine/t228/claims_91_s2.db` is the run that can pass the gate: the stage-2
database carries announcements, annual reports and press releases for the 91 and the new
`speaker_scope`/`dup_of` columns (applied automatically when present).  Until Wolf copies and
reviews it, no stage-C IC is claimed.  The one passing factor is stage B's `claim_count_12m`; its
stage-B ICs (6m 0.0848, t 2.54; 12m 0.1138, t 1.67) are unchanged by this stage.

### 10.5 Limits

- **Capex collapses distinct projects that share a key.**  The rule is per (symbol, segment,
  effective_period), so a call that lists several projects under one period and segment
  (NAVKARCORP's Q1FY26 bullets print 100 / 150 / 900 / 2,359 / 4,000 crore) keeps only the latest
  row for that key.  The factor is the latest stated plan per key, not the sum of every project in
  the announcement; a blank effective period is a single key.
- **Order-repeat detection is textual.**  Two filings of the same order with no shared description
  token (one prints only the value/period table) are counted twice; the 1% / 30-day / text rule is
  conservative on purpose.  MICEL's announcement rows print `inr` (rupees), which the brief's unit
  rule skips, so they never enter the sum.
- **`deck_order_cover` is not the KPI series.**  Only 4 companies carry both; the 0.42 rank
  agreement and 48.5% within-10% share mean the deck total and the store's stated order-book cover
  are different quantities (period, segment or scope), so the factor is not a validation of the
  KPI line.
- **Deck verification is not truth.**  Wolf's hand read put ~4% of verified rows wrong; the
  order-book and capacity rows used here share that error rate, and the capacity total is often
  unlabelled by stage.
- **Selection is unchanged.**  No control draw can be computed for the text/deck factors (the
  sources cover only the 91); every number here remains conditional on "91 companies picked in
  Nov 2026", with stage B's matched control as the only selection measure.
- **No IC is claimed on this run.**  A failed gate is the result; the second run on the widened
  claims database is where the incremental test is applied.

