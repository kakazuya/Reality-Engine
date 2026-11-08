# T-118: which held facts move forward returns (6m / 12m / 24m)

Study run 8 Nov 2026 by Wolf. Ticket T-118, accept Shivam. Objective (Shivam, 8 Nov): predict
6-month to 2-year prices from the least reliable data, so this ranks which extractions are worth
finishing and which to drop.

Code: `reality_engine/research/factor_weights.py`. Tests: `reality_engine/tests/test_factor_weights.py`
(22 passed). Run:

```bash
python -m reality_engine.research.factor_weights --out .tmp/t118    # ~110 s, DuckDB memory_limit 5 GB
```

Outputs (all under `.tmp/t118/`, nothing else is written): `factor_ic.csv`, `fama_macbeth.csv`,
`sector_split.csv`, `coverage_by_year.csv`, `T-118_factor_weights.html`.

## 1. Method

Data: the dated DuckDB snapshot `reality_engine/data/snapshots/truth_2026-11-04.duckdb`, opened
read-only. Tables used: `px_daily` (total-return series `tr_close`, adjusted `adj_close`, traded
value, delivery %), `results_key` (XBRL results filings with `known_at_utc`), `shp_index`
(promoter %), `nse_insider` (insider buy/sell value), `company_industry` (sector) and `index_tri`
(Nifty 500 TRI).

- **Rebalances**: the last trading day of every month, 2020-01-31 to 2026-11-03 (83 dates). The
  brief's 2019-06 start is impossible: `px_daily` begins 2019-01-01, so no company can have the
  250 sessions of history the universe rule requires before 2020-01.
- **Universe per date**: a price that day, median daily traded value over the prior 60 sessions
  >= Rs 1 crore, at least 250 sessions of history. Delisted companies stay while they traded.
  93,057 company-months over 2,266 companies in the built panel (83 rebalances); every statistic in
  sections 4-7 runs on the 2021-01 onward sample, 85,621 company-months and 71 rebalances, with 844
  companies in 2020 rising to 1,757 in 2024.
- **Identity**: `px_daily.entity_id` is the company key (stable across the 561 ISIN changes and
  4,349 symbol changes in the file); filing `trading_isin` maps to it through the price table
  (1,386 of 104,424 filings do not map and are dropped, 1.3%).
- **Reporting basis**: one series per company, never mixed. Consolidated where the company files it
  at least as often as standalone (Standalone and Non-Consolidated are one family). 61,573 of the
  filings survive that choice.
- **TTM**: a quarter's value is the reported quarter figure, else the YTD delta inside one fiscal
  year (`ytd_p - ytd_{p-1}`), else the first-quarter YTD. A TTM needs four consecutive quarters
  (period-end span 250-290 days) and the YoY columns need eight (620-660 days); a gapped window is
  dropped, never padded. Bank revenue is `InterestEarned` when `RevenueFromOperations` is empty.
- **Targets**: forward total return from `tr_close` over 126, 252 and 504 sessions minus the Nifty
  500 TRI over the same window. A company with no price on the horizon date, or a date whose window
  runs past the last session, gets no target. The TRI series ends 2026-10-16, so the last dates drop
  naturally per horizon (63, 57 and 45 usable months).
- **Factors** (1% winsorised and z-scored within date; a sector-neutral z within (date, sector) is
  computed for every factor, NaN when a sector has fewer than 5 names):

| block | factors |
|---|---|
| growth | TTM revenue YoY, TTM PAT YoY, latest-quarter PAT YoY, PAT growth acceleration |
| quality | TTM operating margin, its YoY change, TTM finance cost / revenue |
| valuation | TTM earnings yield, TTM sales yield, log P/S, log P/E (positive PAT only) |
| re-rating | log P/S change 3/6/12m, log P/E change 3/6/12m, 12m price move split into sales growth share and P/S re-rating share |
| sector | sector median log P/S change 12/36m, sector median log P/E change 12/36m, own log P/S minus sector median |
| cyclical peak | TTM operating margin percentile and TTM PAT percentile within the company's own trailing 5 years, and (PAT growth in the top tercile) x (margin percentile > 80%) |
| ownership | promoter % change 1 quarter and 4 quarters (percentage points), insider net buy over the prior 3 months / market cap |
| price | 12-1 month momentum, 1-month reversal, 12-month volatility, log market cap, delivery % 3-month mean |

- **Statistics** per factor x horizon: monthly Spearman IC (mean, Newey-West t with lags = horizon
  in months - 1), hit rate, top-minus-bottom bucket mean excess return, names per month, and the IC
  split by period (2020-2021 / 2022-2026) and by size tercile. Then a Fama-MacBeth cross-sectional
  regression of the excess return on the z-scored factors per month.
- **Joint model sample**: a complete-case regression over all factors leaves ~110 names a month, so
  the joint model takes factors best-covered first, keeping only those that leave 75% of that
  horizon's months with at least 150 names. Sparse factors (insider 22%, delivery) and the P/E
  equivalents of P/S factors are reported univariately. Per horizon: 42/36/24 months, 289/272/259
  names a month (windows 2022-10..2026-03, 2022-10..2025-09, 2022-10..2024-09).

## 2. Point in time

A fact is usable only from the first trading session on which it was public: `known_at_utc`
converted to IST, used that session if it was published at or before 15:30, else from the next
session (weekends and holidays included). TTM availability is the latest `known_at_utc` among the
quarters the TTM uses, and a TTM YoY carries the latest of its eight; a restatement therefore raises
the availability of every window it enters and is never backdated. `merge_asof` attaches the newest
fact whose availability date is on or before the rebalance date.

Two data limits the PIT rule exposes (both are store facts, not code settings):

- **Quarterly results start in 2019.** `results_key` holds 5 filing rows for 2017 and 2,161 for 2018
  (mostly annual), so only 3 companies have eight consecutive quarters by 2019-12-31. Coverage of
  the TTM YoY factors is therefore 12% in 2020 and 71% from 2021 — the 2020 months are excluded from
  every statistic (the run prints the reason), so the studied sample is 2021-01 to 2026-10.
- **Shareholding `known_at` is the 2022 backfill for old quarters.** `shp_index` rows for quarters
  before 2022 carry a 2022+ `known_at_utc` (median lag 18-98 days for 2022+, 745-2,260 days for
  2015-2021), so promoter-change factors are correctly empty before 2022 and 0.69-0.78 covered after.

## 3. Coverage by year

Share of company-months with a value (full table: `.tmp/t118/coverage_by_year.csv`):

| year | rows | companies | rev YoY | PAT YoY | qtr PAT YoY | op margin | earnings yield | P/E | P/S chg 12m | sector P/S chg 36m | margin pctile | peak x growth | promoter 4q | insider |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2020 | 7,436 | 844 | 0.12 | 0.11 | 0.56 | 0.72 | 0.75 | 0.65 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.34 |
| 2021 | 11,418 | 1,203 | 0.71 | 0.58 | 0.76 | 0.82 | 0.87 | 0.75 | 0.45 | 0.00 | 0.02 | 0.02 | 0.00 | 0.34 |
| 2022 | 12,036 | 1,313 | 0.77 | 0.62 | 0.72 | 0.77 | 0.82 | 0.72 | 0.64 | 0.00 | 0.39 | 0.35 | 0.20 | 0.26 |
| 2023 | 13,512 | 1,429 | 0.63 | 0.55 | 0.70 | 0.74 | 0.78 | 0.71 | 0.52 | 0.73 | 0.51 | 0.46 | 0.71 | 0.22 |
| 2024 | 17,035 | 1,753 | 0.71 | 0.63 | 0.75 | 0.79 | 0.85 | 0.76 | 0.57 | 0.75 | 0.57 | 0.50 | 0.72 | 0.19 |
| 2025 | 16,119 | 1,670 | 0.82 | 0.73 | 0.78 | 0.81 | 0.86 | 0.79 | 0.75 | 0.76 | 0.65 | 0.59 | 0.75 | 0.17 |
| 2026 | 15,501 | 1,657 | 0.83 | 0.74 | 0.80 | 0.82 | 0.87 | 0.81 | 0.73 | 0.76 | 0.66 | 0.60 | 0.77 | 0.08 |

P/E is computed only over company-months with positive TTM PAT (75% of the panel; P/S 86%). The
5-year percentile needs 24 months of TTM history, so it starts in 2022 and is a 3-4 year window
until 2024 (TTM history itself starts 2019-12).

## 4. Univariate results, top 10 per horizon

IC is the mean monthly Spearman rank correlation with the forward excess return; t is Newey-West;
Q5-Q1 is the mean top-minus-bottom bucket excess return in that horizon; names/mo is the average
cross-section; the last three columns are the same IC inside each size tercile.

**6 months (63 months)**

| factor | mean IC | t | hit | Q5-Q1 | names/mo | IC sector-neutral | small | mid | large |
|---|---|---|---|---|---|---|---|---|---|
| insider net buy / mcap | +0.061 | +6.03 | 83% | +0.077 | 262 | +0.034 | +0.084 | +0.036 | +0.020 |
| TTM earnings yield | +0.056 | +4.64 | 78% | +0.049 | 983 | +0.036 | +0.040 | +0.063 | +0.056 |
| TTM PAT percentile | +0.046 | +3.87 | 79% | +0.025 | 703 | +0.033 | +0.071 | +0.036 | +0.013 |
| TTM margin percentile | +0.052 | +3.68 | 85% | +0.035 | 662 | +0.041 | +0.044 | +0.043 | +0.062 |
| margin YoY change | +0.032 | +3.61 | 75% | +0.030 | 796 | +0.026 | +0.024 | +0.050 | +0.018 |
| log P/E | -0.056 | -3.33 | 27% | -0.069 | 883 | -0.043 | -0.022 | -0.067 | -0.063 |
| quarter PAT YoY | +0.034 | +3.09 | 73% | +0.040 | 877 | +0.023 | +0.023 | +0.069 | +0.005 |
| promoter % chg 4q | +0.032 | +3.05 | 75% | +0.044 | 769 | +0.043 | +0.050 | +0.041 | +0.020 |
| 1-month reversal | -0.028 | -2.80 | 33% | -0.035 | 1,173 | -0.017 | -0.022 | -0.045 | +0.000 |
| 12-1 momentum | +0.067 | +2.80 | 76% | +0.090 | 1,172 | +0.047 | +0.053 | +0.093 | +0.058 |

**12 months (57 months)**

| factor | mean IC | t | hit | Q5-Q1 | names/mo | IC sector-neutral | small | mid | large |
|---|---|---|---|---|---|---|---|---|---|
| 1-month reversal | -0.051 | -5.77 | 26% | -0.085 | 1,151 | -0.038 | -0.038 | -0.061 | -0.021 |
| TTM earnings yield | +0.071 | +5.65 | 91% | +0.085 | 962 | +0.037 | +0.041 | +0.073 | +0.095 |
| TTM margin percentile | +0.066 | +4.94 | 93% | +0.081 | 632 | +0.049 | +0.063 | +0.032 | +0.100 |
| insider net buy / mcap | +0.074 | +4.81 | 86% | +0.155 | 266 | +0.028 | +0.104 | +0.039 | +0.039 |
| TTM PAT percentile | +0.060 | +4.03 | 80% | +0.064 | 669 | +0.036 | +0.079 | +0.048 | +0.019 |
| log P/E | -0.072 | -3.44 | 18% | -0.130 | 862 | -0.046 | -0.007 | -0.089 | -0.111 |
| promoter % chg 4q | +0.050 | +3.35 | 80% | +0.088 | 734 | +0.051 | +0.048 | +0.053 | +0.047 |
| P/S chg 3m | +0.049 | +2.86 | 67% | +0.101 | 873 | +0.035 | +0.033 | +0.066 | +0.044 |
| PAT growth acceleration | +0.021 | +2.80 | 65% | +0.017 | 835 | +0.010 | +0.013 | +0.028 | +0.015 |
| P/S chg 6m | +0.068 | +2.47 | 75% | +0.131 | 793 | +0.050 | +0.050 | +0.093 | +0.046 |

**24 months (45 months)**

| factor | mean IC | t | hit | Q5-Q1 | names/mo | IC sector-neutral | small | mid | large |
|---|---|---|---|---|---|---|---|---|---|
| sector P/S chg 36m | +0.064 | +14.49 | 90% | +0.002 | 925 | n/a | +0.057 | +0.021 | +0.069 |
| TTM earnings yield | +0.098 | +10.77 | 100% | +0.202 | 899 | +0.059 | +0.028 | +0.101 | +0.173 |
| TTM margin percentile | +0.081 | +7.44 | 100% | +0.217 | 548 | +0.053 | +0.061 | +0.036 | +0.159 |
| sector P/S chg 12m | +0.073 | +6.88 | 80% | +0.098 | 822 | n/a | +0.069 | +0.064 | +0.059 |
| insider net buy / mcap | +0.094 | +5.44 | 96% | +0.356 | 270 | +0.033 | +0.106 | +0.086 | +0.044 |
| log P/E | -0.116 | -4.87 | 0% | -0.351 | 803 | -0.082 | -0.002 | -0.131 | -0.208 |
| TTM PAT percentile | +0.062 | +4.65 | 97% | +0.113 | 576 | +0.030 | +0.084 | +0.059 | +0.023 |
| PAT growth acceleration | +0.024 | +4.46 | 69% | +0.065 | 791 | +0.008 | +0.016 | +0.043 | +0.009 |
| sector P/E chg 36m | -0.039 | -4.30 | 19% | -0.167 | 917 | n/a | +0.029 | -0.023 | -0.061 |
| P/S chg 3m | +0.050 | +3.12 | 69% | +0.172 | 799 | +0.036 | +0.032 | +0.074 | +0.048 |

The full table (all 35 factors x 3 horizons, with the period split and every size tercile) is
`.tmp/t118/factor_ic.csv`. The sector median-change factors show `n/a` for the sector-neutral IC
because they are one number per sector-month: the within-sector z is undefined.

## 5. Joint model (Fama-MacBeth)

Mean cross-sectional coefficient per month on the z-scored factors; t is Newey-West. Rows with
|t| >= 2:

| horizon | factor | mean coef | t | months | names/mo | window |
|---|---|---|---|---|---|---|
| 6m | margin YoY change | +0.0248 | +4.04 | 42 | 289 | 2022-10..2026-03 |
| 6m | promoter % chg 1q | +0.0139 | +2.57 | 42 | 289 | 2022-10..2026-03 |
| 12m | margin YoY change | +0.0429 | +2.53 | 36 | 272 | 2022-10..2025-09 |
| 12m | TTM PAT percentile | -0.0222 | -2.41 | 36 | 272 | 2022-10..2025-09 |
| 24m | own P/S vs sector median | -0.1977 | -3.17 | 24 | 259 | 2022-10..2024-09 |
| 24m | 12-1 momentum | +0.1657 | +2.77 | 24 | 259 | 2022-10..2024-09 |
| 24m | sales yield | -0.1551 | -2.40 | 24 | 259 | 2022-10..2024-09 |
| 24m | 1-month reversal | -0.0732 | -2.22 | 24 | 259 | 2022-10..2024-09 |

Full table with every coefficient: `.tmp/t118/fama_macbeth.csv`. Three cautions: the model has 27
factors on 42 months of overlapping windows, so most coefficients are not significant; valuation
factors are collinear (sales yield and earnings yield flip sign at 24m, read the pair jointly, not
each coefficient); and the window starts 2022-10 because that is where every kept factor is covered.

## 6. The 12-month price move split by sector

Mean log changes over each company's last 12 months, pooled over 2021-2026 (top rows by compression
of the multiple, then the rest):

| sector | company-months | price 12m | sales 12m | P/S 12m | re-rating share |
|---|---|---|---|---|---|
| Forest Materials | 245 | +11.1% | +15.7% | -5.6% | +0.50 |
| Automobile & Auto | 2,747 | +21.6% | +15.2% | +5.9% | +0.68 |
| Capital Goods | 6,490 | +24.3% | +13.4% | +8.3% | +0.77 |
| Metals & Mining | 1,330 | +27.8% | +10.2% | +9.9% | +0.84 |
| Power | 1,087 | +27.8% | +5.9% | +21.6% | +0.86 |
| Consumer Durables | 2,596 | +6.3% | +11.7% | -2.8% | +0.88 |
| Consumer Services | 1,842 | +1.8% | +14.6% | -9.1% | +0.92 |
| Financial Services | 4,620 | +13.3% | +16.4% | -2.8% | +0.97 |
| Information Technology | 2,322 | +14.8% | +15.4% | -6.2% | +1.09 |

Read: IT and Financial Services are the "earnings grew, multiple compressed" case — over the pooled
sample IT sales compounded +15.4% a year while its P/S fell 6.2% a year, so the entire 12-month
price move (and a little more) came from the re-rating share being above 1. Power and Metals are the
opposite: the multiple did the work. The latest rebalance (2026-11-03, IT 49 names, sales +17.8%,
P/S -35.6%, price -22.9%) says the compression is still running for IT; Realty, FMCG, Financial
Services and Consumer Durables also print negative sales shares, i.e. the multiple did more than the
whole move. Full table for both windows: `.tmp/t118/sector_split.csv`.

## 7. What the results say

Ranked by how much of the forward return the data actually explains, per horizon:

1. **Valuation level is the most consistent single factor**: earnings yield (and its mirror P/E) is
   the only factor that is positive and significant at all three horizons and in all three size
   terciles, and its IC grows with the horizon (0.056 -> 0.071 -> 0.098). Cheap beats expensive,
   more so over 2 years, and strongest in large caps at 24m (+0.173).
2. **Insider net buy over the prior 3 months** (not the ticket's list, but a held fact) has the
   highest raw IC at 6m (+0.061, t 6.0) and remains strong at 12m and 24m. It is only available for
   the ~25% of names that filed a disclosure in the window, so treat it as a disclosure-conditional
   signal, not a universe-wide one; it does not survive into the joint model's sample.
3. **The company's own 5-year percentile of operating margin and of TTM PAT are positive at every
   horizon** (margin percentile 0.052 / 0.066 / 0.081). Peak earnings were momentum in 2021-2026,
   not a warning: the ticket's "cyclical peak" trap is not visible here, and the explicit interaction
   (top-tercile PAT growth x margin percentile > 80%) is also positive (0.033 / 0.038 / 0.056, t
   1.8 / 2.1 / 3.0, strongest in large caps). Whatever de-rates IT and the cyclicals, it is not the
   margin level alone.
4. **Re-rating is persistent, valuation is not**: the change in P/S (3m, 6m, 12m) has a positive IC
   at every horizon while the P/S level is negative. A multiple that has been rising tends to keep
   rising over the next 6-12 months, yet the expensive name still gives up the money over 1-2 years.
   That is the "strong results while the stock de-rates" pattern measured the other way round:
   the de-rating is what the 12-24 month horizon punishes.
5. **Sector de-rating is real but unmeasurable at company precision**: the 36-month sector median
   P/S change has the largest t-stat of the study (14.5 at 24m) yet a top-minus-bottom spread of
   +0.002 and no sector-neutral version — it is a between-sector timing effect on ~20 independent
   sector series, so its t is not comparable to a company-level factor. Read the sector split
   (section 6) directly instead of its t-stat. What *is* company-specific is the relative multiple:
   a company priced above its own sector median gives back the most at 24m (IC -0.111, joint
   coefficient -0.198, t -3.2).
6. **Growth is the weakest of the fundamental block**: TTM revenue YoY +0.021 (t 1.8) at 6m and
   nothing beyond (-0.016 at 24m), TTM PAT YoY +0.025 (t 2.3) at 6m and +0.008 at 24m, latest-quarter
   PAT YoY +0.034 (t 3.1) at 6m. The margin *change* is the growth block's best member (t 3.6 at 6m
   and the top joint coefficient at 6m and 12m), and it decays with the horizon.
7. **Promoter % change over 4 quarters is positive at every horizon** (+0.032 / +0.050 / +0.066)
   and the insider and promoter blocks reinforce each other: rising insider ownership is the most
   predictive ownership fact in the store. Caveat: a promoter % can rise mechanically through a
   buyback or fall through an ESOP issue; the store does not separate the two.
8. **1-month reversal and 12-1 momentum are both present** with the expected signs (short-term
   losers rebound, 12-month winners keep winning), which is the standard combination, not a data
   artefact.
9. **Almost nothing else survives**: the operating-margin *level* is flat at 6m and negative at 24m
   (-0.033) — the percentile and the change carry the signal, not the level; finance cost / revenue
   is positive and significant only at 24m (+0.074, t 2.8, and positive in the joint model too, so
   it reads as a leverage/small-cap proxy rather than a cost signal); volatility is negative and
   significant only at 24m (-0.072, t -2.8); size has no stable IC (+0.019 / +0.033 / +0.013);
   delivery % is noise; and the growth-trap interaction is positive rather than negative.

### Which extractions to finish, which to drop

- **Finish first**: earnings and PAT (TTM + quarter, the valuation block is the best bet), the
  operating-margin line (level, change and the own-history percentile), promoter shareholding,
  insider trades (highest return per unit of coverage), and the price/volume history (reversal,
  momentum, size).
- **Keep but cheap**: P/S and P/E levels and their 3/6/12-month changes, sector medians (useful as
  context in section 6, not as a cross-sectional factor), PAT growth acceleration.
- **Drop or deprioritise**: PAT growth acceleration as a headline factor (IC +0.013 to +0.024, the
  smallest of the growth block), the operating-margin level on its own, finance cost / revenue,
  delivery %, volatility, the 12-month sales-share split as a *predictor* (IC -0.001 to +0.012; it
  is a report, not a signal).
- **Not in this snapshot, so still unranked**: ROE/ROCE (results_key carries paid-up capital, not
  book value — a balance sheet is needed), promoter pledge, FPI and mutual-fund holding changes
  (`shp_index` has only promoter/public; the pilot3 `shp_category`/`shp_pledge` tables would supply
  them), and guidance raised or cut (only `pilot3_guidance` holds it). These four are the ticket's
  remaining factors and must not be marked "no effect" — they are not measured here.

## 8. Caveats and look-ahead checks

- **Overlapping windows**: monthly measurement of 6/12/24-month returns overlaps 6/12/24-fold.
  Newey-West with lags = horizon-1 months is used, but the 24m t-stats (23 lags on 45 months) are
  optimistic; treat every 24m t as an upper bound and the IC as the honest number.
- **Sample**: the universe is liquid names only (median Rs 1 crore/day over 60 sessions, 250
  sessions of history), which removes the smallest and newest companies; the survivor question is
  handled by keeping delisted companies while they traded, but a company that stops trading before
  the horizon date gets no target (dropped, not filled).
- **2020 is not in the statistics** (growth coverage 11-12%, section 3); neither the March 2020
  crash nor the 2020-21 re-rating of cheap names is measured, which is why the value result here
  should not be read as a crash-window result.
- **PIT was verified, not assumed**: `test_factor_weights.py` covers the 15:30 boundary, the weekend
  filing, a filing past the last session, a fact known after the rebalance date, TTM from four
  quarters, TTM from a YTD delta when a quarter value is missing, the no-mixing basis rule, forward
  return from `tr_close`, the IC sign on a planted factor and the re-rating decomposition. The one
  real look-ahead bug found while building this (pandas 3 stores datetimes in microseconds, so a
  nanosecond cast stamped every fact in 1970 and the panel never updated) is now a regression test.
- **Data limits**: quarterly `results_key` coverage starts 2019 and shareholding `known_at` is the
  2022 backfill (section 2) — two limits that any 6m-2y study on this snapshot inherits.
- **Sector factors** carry ~20 independent series; their IC and t are reported but not comparable to
  company-level factors, and their sector-neutral IC is undefined.
- **Small-cap noise**: the size terciles show the effects are usually largest in the small tercile
  (insider +0.084 at 6m, PAT percentile +0.071), so a small-cap implementation pays more noise for
  the same signal.

## 9. Files

- `reality_engine/research/factor_weights.py` — panel builder, statistics, CSV/HTML output.
- `reality_engine/tests/test_factor_weights.py` — 22 tests, all on in-memory fixtures.
- Outputs: `.tmp/t118/{factor_ic,fama_macbeth,sector_split,coverage_by_year}.csv` and
  `T-118_factor_weights.html`.
