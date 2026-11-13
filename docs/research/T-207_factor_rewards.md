# T-207: which factors were rewarded at each month-end (round 1)

Study run 13 Nov 2026 by a dsh worker for ticket T-207 (idea I-002, Shivam 13 Nov). It asks a
different question from T-118: not "which factor has the best pooled IC over 2021-2026" but "on each
month-end, which factors had been rewarded over the last 6 / 12 / 24 months, using only returns that
had already been realised by that date". A pooled average uses the future; the rewarded set is what a
decision could actually have known, and its instability is the result.

Code `reality_engine/research/factor_rewards.py`, tests `reality_engine/tests/test_factor_rewards.py`
(11 tests: 8 from round 1, 3 from round 2; all synthetic). It imports the T-118 panel builder
unchanged. Run:

```bash
python -m reality_engine.research.factor_rewards --out .tmp/t207    # ~4.5 min (panel 24 s, then 235 s)
```

Reads the dated DuckDB snapshot `truth_2026-11-04.duckdb` read-only (`memory_limit 5 GB`, as T-118),
caches the panel once as `.tmp/t207/panel.parquet`, and writes only under `--out`:
`rewarded_by_date.csv` (every factor x split x group x horizon x window x month-end state),
`mode.csv` (the share of rated months rewarded), `shifts.csv` (every enter / leave / flip date) and
`walk_forward.csv`. The thresholds are the brief's, fixed before the walk-forward was seen; the
sensitivities are reported beside the main result, never substituted for it. Round 2, declared after
the round-1 tables were seen, is in the final part; it adds measurements only and changes no
round-1 threshold or result.

## 1. Method

- **Panel.** `factor_weights.build_panel` over 2019-06-01..2026-11-03: 93,057 company-months, 2,266
  companies, 83 month-ends; the 2020 months are dropped from every statistic (growth coverage 12%,
  same reason as T-118), leaving 85,621 company-months, 2,253 companies and 71 month-ends
  2021-01-29..2026-11-03. Usable targets: 63 / 57 / 45 month-ends at 6 / 12 / 24 months.
- **Realised IC.** For factor f, horizon h (126 / 252 / 504 sessions) and month-end s, the Spearman
  rank IC of f at s against the forward excess total return from s (Nifty 500 TRI benchmark). The IC is
  computable only when the window ends, so every IC carries `known_date` = session s + h. 72,342
  (split, group, factor, horizon, month) ICs are used.
- **Rewarded set at t.** Over ICs with `known_date` in (t - 24 months, t] (main window; 12 and 36
  months are the sensitivities), a factor is rewarded when the mean IC has |Newey-West t| >= 2 and
  its sign matches the mean in at least 60% of those IC months. Lags = h in months - 1 (5 / 11 / 23).
  Fewer than 12 known months is **not rated**; a rated factor that fails the two tests is
  **unrewarded**. Every row records sign, mean IC, NW t, known months and sign share.
- **Splits** are computed point-in-time at the IC month s, never pooled over time:
  (a) all companies; (b) sector groups from `company_industry`, normalised by case and folded so each
  group has >= 30 names in the months it is rated (merge in section 4); (c) size terciles within each
  month; (d) market regime known at s - Nifty 500 TRI above/below its 200-session mean and trailing
  12-month TRI return positive/negative. A regime cell with fewer than 12 IC months is reported as
  too thin, never pooled.
- **Mode and shifts.** Per factor x horizon x split x group: share of rated months in which it is
  rewarded, split by sign; a "stable" claim is a factor rewarded in >= 70% of its rated months with
  one sign. `shifts.csv` records each transition into, out of, or (in principle) across the set; a
  missing month is not a transition.
- **Walk-forward.** For each month-end t after the first rated window, three scores per company from
  the within-date z of each factor: DYNAMIC = sum(sign x z) over the factors rewarded at t (all
  companies); STATIC = the same set and signs frozen from the first rated window; EQUAL = the same sum
  over all 35 factors with signs fixed in advance from finance convention (below). Realised IC and
  top-minus-bottom fifth excess return are measured over the next h months. The test is the paired
  DYNAMIC minus STATIC difference with its Newey-West t.
- **EQUAL convention** (fixed before results): growth and profitability up; margin change up; finance
  cost / revenue down; earnings and sales yield up; P/S and P/E down; premium to the sector median P/S
  down; P/S and P/E changes up (multiple momentum); the 12m re-rating and sales shares up; sector
  median P/S and P/E changes up; own 5-year margin and PAT percentile down (cyclical-peak warning);
  the peak/growth trap down; promoter 1q/4q change and insider net buy up; 12-1 momentum up; 1-month
  reversal up (the factor is positive after a fall); 12-month volatility and size down; delivery up.
- **Multiplicity.** Every factor x horizon x split x group cell with a rated window is a hypothesis.
  The 70% claim is tested with an exact two-sided binomial against a 50% reward rate over its rated
  months, and Benjamini-Hochberg at 10% is applied across all rated cells. The binomial treats months
  as independent; overlapping horizons violate that, so the survival count is lenient and is reported
  as such.

## 2. Panel gate: T-118 reproduction

The rebuilt panel reproduces the pooled T-118 ICs before anything else runs (stop rule if it does not):

| factor | horizon | T-118 | reproduced | diff |
|---|---|---|---|---|
| TTM earnings yield | 6m | +0.056 | +0.0563 | +0.0003 |
| TTM earnings yield | 12m | +0.071 | +0.0710 | -0.0000 |
| TTM earnings yield | 24m | +0.098 | +0.0981 | +0.0001 |
| TTM margin percentile | 6m | +0.052 | +0.0515 | -0.0005 |
| promoter % change 4q | 12m | +0.050 | +0.0496 | -0.0004 |

## 3. The rewarded set, all companies (window 24 months)

Sign is the sign of the trailing mean IC; share is the share of **rated** months in which the factor
was rewarded with that sign; months is the rated-month count (not the IC months); mean IC is the mean
of the monthly trailing means; t is the median |Newey-West t| of the trailing windows. Listed are the
factors rewarded in at least 70% of rated months; the full 35-factor table is `mode.csv`.

**6 months** (first rated window 2022-07-29, 44 walk-forward months):

| factor | sign | share (months) | mean IC | median \|t\| | BH |
|---|---|---|---|---|---|
| insider net buy / mcap | + | 100% (53) | +0.070 | 5.7 | yes |
| TTM earnings yield | + | 93% (49/53) | +0.059 | 3.4 | yes |
| log P/E | - | 87% (46/53) | -0.062 | 2.5 | yes |
| TTM margin percentile | + | 79% (33/42) | +0.042 | 2.8 | yes |
| TTM PAT percentile | + | 74% (31/42) | +0.042 | 2.4 | yes |
| promoter % change 1q | + | 71% (29/41) | +0.038 | 2.5 | yes |

**12 months** (first rated 2023-01-31, 32 months):

| factor | sign | share (months) | mean IC | median \|t\| | BH |
|---|---|---|---|---|---|
| TTM earnings yield | + | 100% (47) | +0.073 | 4.4 | yes |
| insider net buy / mcap | + | 100% (47) | +0.085 | 6.6 | yes |
| TTM margin percentile | + | 100% (36) | +0.056 | 4.3 | yes |
| promoter % change 4q | + | 100% (30) | +0.059 | 4.6 | yes |
| 1-month reversal | - | 96% (45/47) | -0.054 | 4.7 | yes |
| log P/E | - | 89% (42/47) | -0.081 | 3.6 | yes |
| TTM PAT percentile | + | 86% (31/36) | +0.047 | 3.4 | yes |
| promoter % change 1q | + | 83% (29/35) | +0.054 | 3.9 | yes |
| PAT growth acceleration | + | 77% (36/47) | +0.026 | 2.5 | yes |

**24 months** (first rated 2024-01-31, 8 walk-forward months):

| factor | sign | share (months) | mean IC | median \|t\| | BH |
|---|---|---|---|---|---|
| TTM earnings yield | + | 100% (35) | +0.104 | 10.7 | yes |
| sector median P/S change 12m | + | 100% (35) | +0.079 | 6.6 | yes |
| log P/E | - | 100% (35) | -0.136 | 10.2 | yes |
| TTM margin percentile | + | 100% (24) | +0.070 | 8.3 | yes |
| promoter % change 4q | + | 100% (18) | +0.088 | 4.3 | yes |
| insider net buy / mcap | + | 100% (35) | +0.104 | 13.1 | yes |
| TTM PAT percentile | + | 100% (24) | +0.050 | 6.2 | yes |
| PAT growth acceleration | + | 89% (31/35) | +0.024 | 3.3 | yes |
| TTM finance cost / revenue | + | 89% (31/35) | +0.098 | 9.4 | yes |
| own P/S minus sector median | - | 83% (29/35) | -0.151 | 21.7 | yes |
| promoter % change 1q | + | 83% (19/23) | +0.070 | 5.4 | yes |
| log P/S | - | 80% (28/35) | -0.146 | 9.2 | yes |
| TTM sales yield | + | 80% (28/35) | +0.145 | 9.4 | yes |
| peak-growth trap | + | 75% (18/24) | +0.043 | 2.2 | **no** |
| TTM revenue YoY | - | 71% (25/35) | -0.038 | 3.5 | yes |
| 12-month volatility | - | 71% (25/35) | -0.051 | 2.7 | yes |

Six factors are stably rewarded at **all three** horizons: TTM earnings yield (+), log P/E (-), TTM
margin percentile (+), TTM PAT percentile (+), promoter % change 1q (+) and insider net buy (+). The
PAT-percentile and margin-percentile rows have only 42 / 36 / 24 rated months because the 5-year
history starts in 2022; promoter 4q is thinner still (36 / 30 / 18). The 24-month t is an upper bound:
the window holds at most 24 ICs and uses 23 lags.

## 4. Sector groups and size terciles

`company_industry` carries 23 sector labels after case/space normalisation (24 including the
unclassified group). A sector stays its own group when it has >= 30 names in at least 12 months (the
rating minimum); otherwise it is folded into "Other (merged)". Sector ICs use only months with >= 30
names, so a group is never rated on a thinner month. 24% of company-months (23.8%) have no
`company_industry` sector and are excluded from the sector split (they stay in all-companies, size and
regime). Nine sectors merged: Construction Materials, Diversified, Forest Materials, Healthcare
Services, Media Entertainment & Publication, Oil Gas & Consumable Fuels, Power, Telecommunication,
Utilities. The other group has >= 85 names a month. Sector months with >= 30 names: 71 of 71 for
Automobile, Capital Goods, Chemicals, Consumer Durables, FMCG, Financial Services, Healthcare; 68 IT;
56 Services; 51 Consumer Services; 50 Construction; 48 Textiles; 36 Metals & Mining; 34 Realty. One
caveat that applies to T-118 too: `company_industry` is the *current* label, so applying it to 2021
is a mild look-ahead; the sector split is a diagnostic of where a reward is locally steady, not a
tradable sector rotation.

Stable-70 cells and the rated months at each horizon (a "cell" is a factor inside that group; the full
per-factor shares are in `mode.csv`):

| group | rated 6m / 12m / 24m | stable 6m | stable 12m | stable 24m | 12m-only vs all companies |
|---|---|---|---|---|---|
| Automobile & Auto | 53 / 47 / 35 | 2 | 2 | 8 | re-rating share, sales share |
| Capital Goods | 53 / 47 / 35 | 0 | 4 | 12 | finance cost, margin change |
| Chemicals | 53 / 47 / 35 | 1 | 4 | 7 | P/S, P/S vs sector, sales yield |
| Construction | 32 / 26 / 14 | 4 | 5 | 1 | margin, margin change, size |
| Consumer Durables | 53 / 47 / 35 | 1 | 6 | 7 | margin change, peak trap, P/S, P/S vs sector, sales yield, PAT YoY |
| Consumer Services | 33 / 27 / 15 | 3 | 9 | 4 | delivery, momentum, P/S, P/S vs sector, sales yield |
| FMCG | 53 / 47 / 35 | 0 | 1 | 1 | - |
| Financial Services | 53 / 47 / 35 | 0 | 1 | 5 | - |
| Healthcare | 53 / 47 / 35 | 1 | 1 | 2 | delivery |
| Information Technology | 50 / 46 / 34 | 1 | 8 | 7 | P/S chg 3m, P/S, P/S vs sector, sales yield, PAT YoY, revenue YoY |
| Metals & Mining | 18 / 12 / 0 | 0 | 0 | 0 | - |
| Other (merged) | 53 / 47 / 35 | 4 | 7 | 10 | margin, P/S, P/S vs sector, sales yield |
| Realty | 18 / 11 / 0 | 1 | 0 | 0 | - |
| Services | 38 / 32 / 20 | 2 | 9 | 2 | finance cost, momentum, margin, P/S, P/S vs sector, sales yield |
| Textiles | 34 / 28 / 16 | 1 | 5 | 1 | margin, P/S, P/S vs sector, sales yield, volatility |

No factor is stably rewarded at all three horizons **inside any named sector**: the intersection is
empty for every named sector (only the merged bucket has one, and it is a grab bag). The sector split
therefore says where a factor is locally steady for one horizon, not that a sector has a durable law:
Auto and Capital Goods are value/quality at 24m, IT and Services are quality/value at 12m, and those
sets differ from each other. Metals & Mining and Realty have no 24m window at all (12 and 11 rated
months), so their 24m cells are too thin to read.

**Size terciles** (within each month; each tercile is hundreds of names):

| tercile | stable 6m | stable 12m | stable 24m | stable at all three horizons |
|---|---|---|---|---|
| small | 6 | 8 | 12 | insider net buy, PAT percentile, promoter 1q |
| mid | 8 | 12 | 14 | PAT percentile, log P/E, promoter 1q, promoter 4q |
| large | 0 | 3 | 12 | none |

The value/quality/ownership set is broadly the same in small and mid; the large tercile has no stable
factor at 6m and only finance cost, sales yield and P/S at 12m, but by 24m it holds twelve, including
earnings yield, P/E, margin and PAT percentile. The 6m large-cap cell is empty because the 6m ICs of
those factors are not significant at 70% of months; it is a real result, not a data gap.

## 5. Market regime

TRI cells at month-ends: above 200-session mean and 12m return positive (`above_up`) 50, below/up 12,
above/down 4, below/down 3; 2 month-ends after the TRI series ends (2026-10-16) have no label. IC
months actually available per horizon:

| cell | 6m | 12m | 24m | verdict |
|---|---|---|---|---|
| above_up | 47 | 44 | 39 | measurable |
| below_up | 10 | 8 | 5 | too thin (< 12) |
| above_down | 4 | 4 | 1 | too thin |
| below_down | 2 | 1 | 0 | too thin |

Only `above_up` has a rated window; the other three cells cannot support a rewarded set and are not
pooled. The measurable cell is a subset of the all-company set at every horizon: 4 stable factors at
6m (insider, PAT percentile, earnings yield, margin percentile), 8 at 12m (the all-company 12m set
minus PAT acceleration), and 12 at 24m (the all-company 24m set minus PAT acceleration, promoter 1q,
revenue YoY and volatility). With 39-47 of the 63 / 57 / 45 usable months in one cell, this study
cannot separate "rewarded in a bull market" from "rewarded in this sample".

## 6. Shifts

In the all-companies set (window 24) the rewarded set changed on 35 enter / 43 leave dates at 6m, 40 /
44 at 12m and 22 / 20 at 24m. **No factor ever flips sign** anywhere in the study: every transition is
an enter or a leave. The full dated list is `shifts.csv`; the most restless factors are the P/E and P/S
changes and the growth block (P/S chg 3m 6 shifts at 12m, P/S chg 3m 4 at 6m, PAT acceleration 6 at
12m, sales share 6 at 12m, revenue YoY 5 at 6m). Examples of what moved and when:

- 6m earnings yield: enter 2022-08-30, leave 2022-11-30, re-enter 2023-02-28 and stay (3
  transitions); it is still stable at 93% of months, so the shifts are the minority.
- 6m P/E change 12m: 2 entries and 3 exits between 2022-10 and 2026-10; never stably rewarded.
- 12m momentum: two entries and two exits between 2023-02 and 2026-08, never reaching 70%.
- 12m reversal: one entry (2023-03-31) and no exit; 96% of rated months.
- 12m volatility: one entry (2026-05-29) and no exit; too new to be stable.
- 24m momentum: two entries and one exit between 2024-07 and 2026-07; only 46% of months.

## 7. Walk-forward: does choosing by trailing reward beat a fixed choice?

Scores are the sum of sign x within-date z over the factors in each set; months are month-ends after
the first rated window. IC is the rank IC of the score against the next-h excess return; Q5-Q1 is the
top-minus-bottom fifth mean excess return in that horizon. t is Newey-West with 5 / 11 / 23 lags.
The frozen STATIC set has 16 / 17 / 19 factors at 6 / 12 / 24 months; DYNAMIC averages
13.8 / 17.9 / 17.3 factors a month over the test months. (Round 1 printed 21.1 at 24m because it
averaged evaluation dates with no realised 24m outcome; the test-month count is 17.3 and no IC or
spread in this table changes.)

| horizon | score | months | mean IC | t (IC) | IC hit | mean Q5-Q1 | t (Q5-Q1) | Q5-Q1 hit |
|---|---|---|---|---|---|---|---|---|
| 6m | DYNAMIC | 44 | +0.053 | +2.16 | 66% | +0.060 | +1.90 | 66% |
| 6m | STATIC | 44 | +0.011 | +0.30 | 55% | +0.067 | +1.85 | 64% |
| 6m | EQUAL | 44 | +0.043 | +2.54 | 75% | +0.051 | +3.25 | 80% |
| 6m | DYNAMIC-STATIC | 44 | +0.042 | +1.76 | 68% | -0.006 | -0.29 | 52% |
| 12m | DYNAMIC | 32 | +0.064 | +1.85 | 78% | +0.128 | +1.80 | 78% |
| 12m | STATIC | 32 | +0.001 | +0.02 | 41% | +0.080 | +0.87 | 44% |
| 12m | EQUAL | 32 | +0.035 | +1.62 | 69% | +0.082 | +1.79 | 75% |
| 12m | DYNAMIC-STATIC | 32 | +0.063 | +2.07 | 84% | +0.048 | +1.20 | 69% |
| 24m | DYNAMIC | 8 | -0.059 | -15.7 | 0% | -0.105 | -9.42 | 0% |
| 24m | STATIC | 8 | -0.055 | -14.8 | 0% | -0.096 | -10.9 | 0% |
| 24m | EQUAL | 8 | +0.010 | +2.34 | 50% | +0.025 | +4.62 | 88% |
| 24m | DYNAMIC-STATIC | 8 | -0.004 | -1.06 | 38% | -0.008 | -0.58 | 38% |

Read it carefully:

- **6m and 12m:** DYNAMIC has a higher mean IC than the frozen first-window set (+0.053 vs +0.011;
  +0.064 vs +0.001) and the paired difference is positive, but it is significant only at 12m (t 2.07);
  6m is t 1.76. On the economic top-minus-bottom spread the 6m difference is slightly negative
  (-0.006, t -0.29) and the 12m difference (+0.048) has t 1.20. So trailing selection improves the
  rank ordering of stocks at 6-12m, not convincingly the long-short payoff.
- **24m:** the exercise fails out of sample. Both dynamic and frozen sets have a negative IC in all 8
  test months; only the fixed-convention EQUAL score is positive. Those 8 months are highly
  overlapping 24-month windows, so their t-values (lags 23 on 8 observations) are not interpretable;
  the sign is the finding, not the t.
- **EQUAL is a strong, cheap baseline:** it is positive at every horizon (IC +0.043 / +0.035 / +0.010)
  and has the best 24m spread. DYNAMIC beats it on both IC and spread at 6m (+0.053 vs +0.043 IC,
  +0.060 vs +0.051 Q5-Q1) and 12m (+0.064 vs +0.035, +0.128 vs +0.082); no test of that difference is
  in the table, so read it as descriptive. At 24m EQUAL is the only positive score. The honest summary:
  **the trailing-reward dynamic is worth about +0.04 to +0.06 of rank IC over a frozen first-window
  choice at 6-12 months, but the paired difference is significant only at 12m, it is not confirmed by
  a significantly better long-short payoff, and at 24 months it lost money.**

## 8. Multiplicity

2,006 group cells (factor x horizon x split x group) were evaluated at window 24; 1,454 of them had a
rated window (>= 12 known IC months) and enter the correction, over 420 factor x horizon x split
cells. 280 cells claim a 70% reward; **264 survive Benjamini-Hochberg at 10%** (exact two-sided
binomial against 50%, m = 1,454). Survival by block:

| split | horizon | survive / claims |
|---|---|---|
| all | 6m | 6 / 6 |
| all | 12m | 9 / 9 |
| all | 24m | 15 / 16 |
| sector | 6m | 16 / 21 |
| sector | 12m | 56 / 62 |
| sector | 24m | 66 / 67 |
| size | 6m | 14 / 14 |
| size | 12m | 23 / 23 |
| size | 24m | 37 / 38 |
| regime | 6m | 4 / 4 |
| regime | 12m | 7 / 8 |
| regime | 24m | 11 / 12 |

The 16 cells that do not survive are mostly short-history sector cells: Services finance cost (6m),
Construction sales yield / P/S / P/S vs sector (6m), IT margin percentile (6m), Consumer Durables PAT
YoY (12m), Construction margin change (12m), the Textiles sales yield / P/S / P/S-vs-sector trio
(12m), Services promoter 4q (12m), the regime cell's promoter 1q (12m), Automobile P/S chg 12m (24m),
the all-company peak trap (24m), the regime cell's peak trap (24m) and large-cap promoter 4q (24m).
The binomial's independence assumption is false for overlapping horizons, so 264 is an upper bound on
the number of genuinely stable cells; it is still the number that survives the stated procedure.

**Round-2 placebo (beside the 15/16).** 20 fixed-seed cross-sectional permutations of each factor
within each date, rerunning the all-companies reward rule: **0.10 / 0.30 / 0.95** factors reach the
70% claim per run at 6 / 12 / 24 months (max 1 / 2 / 3), against **6 / 9 / 16** observed. The
permutation therefore explains about 2% / 3% / 6% of the observed claims on average, and at most
17% / 22% / 19% if every run hit its maximum. The 70% claims are not a cross-sectional-permutation
artifact. Details and the run table are in R2.6.

## 9. What is stable, what shifted, what is too thin

**Stable.** Value (earnings yield and P/E at every horizon; sales yield and the premium to the sector
median at 24m), the company's own 5-year operating-margin and PAT percentiles, promoter ownership
change (1q at every horizon, 4q at 12/24m) and insider net buying are rewarded in at least 70% of rated
months at every horizon, with 93-100% shares for the three most stable, and survive the correction. The
24m signs are the same as T-118's pooled ranking: cheap, profitable, own-history-high margin, rising
ownership win; expensive, high P/S relative to sector, high volatility and (weakly) revenue growth lose.

**Shifted.** Growth is the least stable block. TTM revenue YoY is rewarded in only 28% of 6m and 21%
of 12m months (and 71% of 24m months with a negative sign); latest-quarter PAT YoY 34% at 6m; PAT
acceleration 23% at 6m but 77% at 12m and 89% at 24m. Momentum enters and leaves (53% at 6m, 36% at
12m, 46% at 24m), while 1-month reversal is stable-negative only at 12m (96%) and not at 6m (64%) or
24m (54%). P/E and P/S changes are never stable (0-64% across horizons). Nothing flips sign: the
instability is on/off, not reversal.

**Too thin to say.** Only one of the four market-regime cells has enough realised months (above_up);
the other three have 0-10 IC months and are reported, not pooled, so "rewarded in a bear market" is
untested here. The 24m walk-forward has 8 overlapping months and its t is meaningless; the 24m trailing
window has at most 24 ICs with 23 lags, so every 24m t is an upper bound. Metals & Mining and Realty
have no 24m rated window; Construction, Consumer Services, Services and Textiles have 14-20 rated
months at 24m, so their 24m claims rest on about a year and a half of information. Sector and regime
claims with 12-18 rated months can reach the 70% bar by a handful of months.

## 10. Extraction worth finishing / not shown to matter

From the tables above only (not from finance intuition):

- **Worth finishing:** TTM earnings and PAT (earnings yield, PAT percentile, margin percentile) - the
  most consistent block across all three horizons (sector subsets do not repeat the full set); the
  operating-margin line (its own-history percentile, not the level); promoter shareholding (1q and 4q
  change); insider trades (most stable factor at 6m, but only ~25% of names, so a
  disclosure-conditional signal); price history for 12m reversal and 24m volatility; the P/S level and
  the premium to the sector median at 24m.
- **Not shown to matter as a stable reward:** delivery %, the 12m re-rating/sales-share decomposition,
  P/E and P/S changes (3/6/12m), sector median P/E change, TTM revenue growth at 6-12m, and the
  peak/growth-trap interaction (positive, not negative, and it fails BH at 24m). Finance cost / revenue
  is stable only at 24m and reads as a leverage/small-cap proxy, as in T-118. This is "not stably
  rewarded in this sample", not "no effect": T-118's pooled t-stats for several of these are real, but
  the reward was not stable enough to be selected at a month-end.

## 11. Factors still unmeasured

The snapshot does not hold these, so they are **not measured**, not "no effect"; each names the table
that would supply it:

| factor | why not measured | table needed |
|---|---|---|
| ROE, ROCE | the snapshot has paid-up capital and face value but no book equity or capital employed | a balance-sheet results table (equity, capital employed) in the snapshot |
| promoter pledge | `shp_index` holds only promoter % and public % | `shp_pledge` (pilot3 stores) |
| FPI holding change | `shp_index` has no category rows | `shp_category`, `fpi_total` |
| mutual-fund holding change | same | `shp_category` |
| guidance raised or cut | no guidance series in the snapshot | `pilot3_guidance` |

The 12-month sales-share split is measured but is not a stable selector; the sector median P/S change
is stable at 24m but is a ~20-series timing variable, not a company-level factor (T-118's caveat).
ROE/ROCE would need the balance sheet for every quarter, not a year-end snapshot, to keep the point
in time honest.

**Round 2 (R2.7) does not change this section.** The stable set still needs only results P&L
(revenue, PAT, operating margin), promoter holding, insider trades and prices; valuation and the
sector-relative multiple are computed from those same inputs plus the held industry label.

## 12. Files and checks

- `reality_engine/research/factor_rewards.py` - panel load/build, realised IC, rewarded set, splits,
  mode/shifts, walk-forward, BH.
- `reality_engine/tests/test_factor_rewards.py` - 11 synthetic tests: the round-1 eight (1970 date bug
  guard, the session a forward window ends on, a planted reward that only flips after its horizon, a
  future IC that never enters the window, the 12-month rating floor, DYNAMIC == STATIC when nothing
  changes, the sector merge, BH) plus three round-2 tests (block score equals plain with one factor
  per block, PERSISTENT ignores a state dated after t, the placebo preserves each date's value
  distribution).
- `python -m pytest reality_engine/tests/test_factor_rewards.py reality_engine/tests/test_factor_weights.py -q --basetemp=.tmp/pt1`
  -> 33 passed (11 new + 22 T-118, which is imported unchanged).
- Outputs `.tmp/t207/{rewarded_by_date,mode,shifts,walk_forward}.csv`, the round-2
  `round2_blocks.csv` and `staleness.csv`, and (with `--placebo`) `placebo.csv` and
  `placebo_factors.csv`; the cached `panel.parquet`.
  `rewarded_by_date.csv` carries `window` = 12 / 24 / 36; the main tables above use 24.
- `python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('docs/research/T-207_factor_rewards.md').exists() else 1)"`
  (the ticket's accept command).

---

# Round 2 (declared after round 1 was seen)

Round 1 asked whether the 24-month walk-forward loses because (a) a block of factors is wrong, (b)
collinear counting lets five correlated anti-growth factors outvote the stable ones, or (c) the 24m
set is simply too stale to select on. Nothing in round 1 is changed below: the thresholds are the
same, every factor that was in a set stays in it, and no factor is dropped or re-weighted because it
hurt. The only additions are the block decomposition, the block-balanced and PERSISTENT scores, the
staleness/cross test and the placebo. Run:

```bash
python -m reality_engine.research.factor_rewards --out .tmp/t207             # 261 s, round-1 + R2.1-R2.5
python -m reality_engine.research.factor_rewards --out .tmp/t207 --placebo   # 520 s total, placebo 257 s
```

## R2.1 What made the 24m composite negative

Blocks are T-118's (growth, quality, valuation, re-rating, sector, cyclical peak, ownership, price).
For each test month the DYNAMIC set's factors are grouped by block, `sign x z` is averaged inside
each block, and the block score's rank IC is measured against the 24m outcome. "Factors" is the mean
number of that block's factors in the set; a block absent from the set in a month has no score.

| block | factors in set | months | mean IC | NW t | hit |
|---|---|---|---|---|---|
| growth | 4.0 | 8 | -0.092 | -26.5 | 0% |
| quality | 2.6 | 8 | -0.094 | -18.8 | 0% |
| price | 1.4 | 8 | -0.157 | -7.0 | 0% |
| re-rating | 2.1 | 8 | -0.046 | -3.9 | 13% |
| valuation | 4.0 | 8 | +0.018 | +8.1 | 88% |
| ownership | 1.0 | 8 | +0.068 | +14.8 | 100% |
| sector | 2.1 | 8 | +0.003 | +1.0 | 63% |
| cyclical peak | 0 | 0 | - | - | - |

The cyclical-peak block was not in the 24m DYNAMIC set during the eight test months (it enters the
set only later, on evaluation dates with no realised 24m outcome), so it cannot be decomposed there.
The same block mean ICs for the shorter horizons (not the focus; months are the non-empty block
scores, so a block absent from the set in some months has fewer):

| block | 6m IC | 6m months | 12m IC | 12m months |
|---|---|---|---|---|
| growth | +0.028 | 26 | +0.045 | 30 |
| quality | +0.026 | 38 | -0.009 | 32 |
| valuation | +0.043 | 44 | +0.039 | 32 |
| re-rating | +0.033 | 44 | +0.028 | 26 |
| sector | +0.038 | 26 | +0.021 | 30 |
| cyclical peak | +0.070 | 25 | +0.087 | 22 |
| ownership | +0.033 | 44 | +0.046 | 32 |
| price | +0.022 | 42 | +0.039 | 32 |

**Reading.** Four blocks made the 24m composite negative: growth (-0.092), quality (-0.094), price
(-0.157) and re-rating (-0.046). They carried 10.1 of the 17.25 factors in the average set (59%),
while the positive blocks - valuation (+0.018, 4.0 factors), ownership (+0.068, 1.0) and sector
(+0.003, 2.1) - carried 7.1 (41%). The plain sum weights by factor count, so the negative blocks
outvote the positive ones. This is the direct answer to (a): it is a block/sign failure, not noise in
one factor. The ownership block is only one factor (insider, ~276 names) in these months, which is
why its strong +0.068 has little weight.

## R2.2 Block-balanced scores

`DYNAMIC_BLOCK` / `STATIC_BLOCK` / `EQUAL_BLOCK` average `sign x z` inside each block and then sum the
block means, so every block contributes equally instead of by its factor count. `PERSISTENT` is in
R2.3; `CROSS_6M` / `CROSS_12M` in R2.5. Same metrics as the round-1 table.

**24 months (8 test months, all values are the same monthly observations as round 1):**

| score | months | mean IC | t (IC) | IC hit | mean Q5-Q1 | t (Q5-Q1) | Q5-Q1 hit | mean factors |
|---|---|---|---|---|---|---|---|---|
| DYNAMIC | 8 | -0.059 | -15.7 | 0% | -0.105 | -9.42 | 0% | 17.3 |
| DYNAMIC_BLOCK | 8 | -0.088 | -6.93 | 0% | -0.103 | -9.88 | 13% | 17.3 |
| STATIC | 8 | -0.055 | -14.8 | 0% | -0.096 | -10.9 | 0% | 19.0 |
| STATIC_BLOCK | 8 | -0.096 | -12.8 | 0% | -0.093 | -5.74 | 0% | 19.0 |
| EQUAL | 8 | +0.010 | +2.34 | 50% | +0.025 | +4.62 | 88% | 35.0 |
| EQUAL_BLOCK | 8 | +0.016 | +3.74 | 88% | +0.033 | +8.46 | 88% | 35.0 |
| PERSISTENT | 0 | - | - | - | - | - | - | - |
| CROSS_6M | 8 | +0.033 | +7.00 | 75% | -0.025 | -2.20 | 38% | 18.4 |
| CROSS_12M | 8 | -0.004 | -0.88 | 50% | -0.030 | -2.11 | 25% | 16.0 |

**6m and 12m (new scores, full metrics):**

| horizon | score | months | mean IC | t (IC) | IC hit | mean Q5-Q1 | t (Q5-Q1) | Q5-Q1 hit |
|---|---|---|---|---|---|---|---|---|
| 6m | DYNAMIC | 44 | +0.053 | +2.16 | 66% | +0.060 | +1.90 | 66% |
| 6m | DYNAMIC_BLOCK | 44 | +0.060 | +2.63 | 77% | +0.067 | +2.09 | 77% |
| 6m | STATIC_BLOCK | 44 | +0.017 | +0.46 | 50% | +0.062 | +1.61 | 64% |
| 6m | EQUAL_BLOCK | 44 | +0.041 | +2.89 | 80% | +0.044 | +3.07 | 80% |
| 6m | PERSISTENT | 34 | +0.028 | +1.21 | 59% | +0.039 | +1.54 | 59% |
| 6m | PERSISTENT_BLOCK | 34 | +0.039 | +1.45 | 62% | +0.049 | +1.65 | 68% |
| 12m | DYNAMIC | 32 | +0.064 | +1.85 | 78% | +0.128 | +1.80 | 78% |
| 12m | DYNAMIC_BLOCK | 32 | +0.079 | +2.46 | 78% | +0.164 | +2.23 | 84% |
| 12m | STATIC_BLOCK | 32 | -0.003 | -0.07 | 38% | +0.087 | +0.85 | 38% |
| 12m | EQUAL_BLOCK | 32 | +0.033 | +2.27 | 75% | +0.056 | +1.72 | 72% |
| 12m | PERSISTENT | 22 | -0.005 | -0.22 | 50% | -0.008 | -0.63 | 41% |
| 12m | PERSISTENT_BLOCK | 22 | +0.010 | +0.44 | 55% | +0.016 | +0.95 | 55% |

Block-balanced is better at 6m (+0.060 vs +0.053) and at 12m (+0.079 vs +0.064), and worse at 24m
(-0.088 vs -0.059). The paired differences are in R2.4; the 12m gain is the only one with a
comfortable t. It does not rescue 24m: equalizing the blocks makes the loss slightly larger, because
the four negative blocks are the majority (four of seven).

## R2.3 PERSISTENT: the expanding mode as a selector

At t, a factor is in PERSISTENT when one sign holds in at least 70% of its **rated states up to t**
(an expanding history of the round-1 state series, only states dated on or before t, at least 12 rated
months). This is the "mode" selector, not the trailing-window set.

| horizon | first persistent month | months | mean IC | t (IC) | mean Q5-Q1 | t (Q5-Q1) | mean factors |
|---|---|---|---|---|---|---|---|
| 6m | 2023-06 | 34 | +0.028 | +1.21 | +0.039 | +1.54 | 9.7 |
| 12m | 2023-12 | 22 | -0.005 | -0.22 | -0.008 | -0.63 | 11.6 |
| 24m | 2024-12 | 0 | - | - | - | - | - |

PERSISTENT is **not testable at 24m**: it needs 12 rated states, the first 24m state is 2024-01, so
the first persistent set is 2024-12 - after the last month with a realised 24m outcome (2024-09).
At 6m and 12m it is not a better selector: PERSISTENT-EQUAL is +0.005 at 6m and -0.014 at 12m, and
PERSISTENT-DYNAMIC is -0.012 at 6m and -0.033 at 12m (t -2.03). The block-balanced persistent score
is slightly better than plain persistent (+0.039 vs +0.028 at 6m; +0.010 vs -0.005 at 12m) but still
does not beat the trailing-window DYNAMIC. So "use the mode" is not the missing rule.

## R2.4 Paired differences

Mean monthly difference of the left minus the right score; months is the overlap; t is Newey-West
with 5 / 11 / 23 lags. The 24m t-values are mechanical: eight overlapping 24-month windows, so they
show direction, not independent evidence.

| pair | horizon | months | mean ΔIC | t (ΔIC) | mean ΔQ5-Q1 | t (ΔQ5-Q1) |
|---|---|---|---|---|---|---|
| DYNAMIC-EQUAL | 6m | 44 | +0.010 | +0.65 | +0.009 | +0.44 |
| DYNAMIC-EQUAL | 12m | 32 | +0.029 | +1.44 | +0.045 | +1.52 |
| DYNAMIC-EQUAL | 24m | 8 | -0.070 | -13.0 | -0.130 | -11.4 |
| PERSISTENT-EQUAL | 6m | 34 | +0.005 | +0.34 | +0.005 | +0.26 |
| PERSISTENT-EQUAL | 12m | 22 | -0.014 | -1.14 | -0.031 | -3.64 |
| PERSISTENT-DYNAMIC | 6m | 34 | -0.012 | -1.14 | +0.002 | +0.15 |
| PERSISTENT-DYNAMIC | 12m | 22 | -0.033 | -2.03 | -0.042 | -1.85 |
| DYNAMIC_BLOCK-DYNAMIC | 6m | 44 | +0.006 | +1.40 | +0.006 | +1.07 |
| DYNAMIC_BLOCK-DYNAMIC | 12m | 32 | +0.015 | +4.43 | +0.036 | +4.07 |
| DYNAMIC_BLOCK-DYNAMIC | 24m | 8 | -0.028 | -2.99 | +0.002 | +0.12 |
| STATIC_BLOCK-STATIC | 6m | 44 | +0.006 | +1.01 | -0.005 | -0.70 |
| STATIC_BLOCK-STATIC | 12m | 32 | -0.004 | -1.13 | +0.007 | +0.65 |
| STATIC_BLOCK-STATIC | 24m | 8 | -0.040 | -5.99 | +0.004 | +0.29 |
| EQUAL_BLOCK-EQUAL | 6m | 44 | -0.002 | -0.34 | -0.007 | -1.64 |
| EQUAL_BLOCK-EQUAL | 12m | 32 | -0.002 | -0.26 | -0.027 | -1.84 |
| EQUAL_BLOCK-EQUAL | 24m | 8 | +0.006 | +3.57 | +0.008 | +1.79 |
| CROSS_6M-DYNAMIC | 24m | 8 | +0.092 | +40.1 | +0.080 | +5.08 |
| CROSS_12M-DYNAMIC | 24m | 8 | +0.055 | +12.6 | +0.075 | +7.10 |

## R2.5 Staleness and the cross-horizon test

Age is the calendar-month distance from the IC's start date to the test month; a 6m IC is at least
6 months old when known, a 24m IC at least 24. "Newest" and "oldest" are the freshest and stalest IC
start dates in the trailing 24-month window at each test month. Full per-month table:
`staleness.csv`.

| horizon | test months | newest age, mean (min-max) | oldest age, mean (min-max) |
|---|---|---|---|
| 6m | 44 | 6.8 (6-7) | 28.5 (19-30) |
| 12m | 32 | 13.0 (13) | 33.9 (25-36) |
| 24m | 8 | 25.0 (25) | 40.5 (37-44) |

So the 24m set at a 2024 test month is learned from ICs that started in 2021-2022, 25-44 months
earlier; the 6m set is learned from ICs 6-30 months old. The cross test applies the 6m and 12m
rewarded sets at t to the same 24m outcome (R2.2 rows CROSS_6M / CROSS_12M):

- CROSS_6M: mean IC +0.033 (t 7.0), Q5-Q1 -0.025; paired against the 24m DYNAMIC: +0.092 IC
  (t 40.1), +0.080 Q5-Q1 (t 5.08).
- CROSS_12M: mean IC -0.004 (t -0.88), Q5-Q1 -0.030; paired against DYNAMIC: +0.055 IC (t 12.6),
  +0.075 Q5-Q1 (t 7.10).
- The 24m DYNAMIC itself: mean IC -0.059, Q5-Q1 -0.105.

The fresher 6m set ranks the 24m outcome positively while the stale 24m set ranks it negatively; the
12m set is neutral. Freshness fixes the rank ordering, but even the 6m set's Q5-Q1 is negative, so it
does not fix the tails. With eight overlapping outcomes, the paired t is not independent evidence;
the sign and the ordering are the result.

## R2.6 Placebo: the false-claim rate

Twenty fixed-seed runs (`PLACEBO_SEED = 20261113`, run r = seed + r). In each run every factor's
non-null values are permuted across companies within each date, the target and the null mask are
kept, and the all-companies reward rule (window 24) is rebuilt. A factor counts when it reaches the
70% claim in that run. `placebo.csv` has the per-run counts, `placebo_factors.csv` the per-factor
detail; the placebo itself took 257 s.

| horizon | observed stable claims | placebo mean | placebo max | mean share of observed | max share |
|---|---|---|---|---|---|
| 6m | 6 | 0.10 | 1 | 1.7% | 17% |
| 12m | 9 | 0.30 | 2 | 3.3% | 22% |
| 24m | 16 | 0.95 | 3 | 5.9% | 19% |

The cross-sectional permutation preserves each date's factor distribution and destroys the
factor-return link. It produces at most three stable factors in any run at 24m, against 16 observed;
on average it explains 2-6% of the round-1 claims. The 16 24m claims (15 of them surviving BH) are
therefore not an artifact of the cross-sectional permutation. It does **not** test the time-series
stability of the reward (the permutation keeps each factor's month-to-month pattern), which is the
remaining limitation.

## R2.7 Three-line reading of 24m, and what it means for extraction

1. **A block/sign failure, not collinear counting.** Growth (-0.092), quality (-0.094), price
   (-0.157) and re-rating (-0.046) were negative in all eight test months; valuation, ownership and
   sector were positive but had 7.1 of 17.25 factors. Equalizing the blocks made the 24m IC worse
   (-0.088 vs -0.059; paired -0.028, t -2.99), so the problem is the signs learned from the 2021
   start dates, not that five correlated factors outvoted three.
2. **Staleness is the binding constraint.** The 24m window's ICs are 25-44 months old; applying the
   6-30-month-old 6m set to the same 24m outcome gives +0.033 (t 7.0) instead of -0.059, though its
   Q5-Q1 is still negative (-0.025). The 12m set is neutral (-0.004). Ten of the 24m set's 17.25
   factors were in the four negative blocks.
3. **The mode is not the missing selector.** PERSISTENT is untestable at 24m (it starts 2024-12,
   after the last outcome in 2024-09) and at 6m/12m it is no better than DYNAMIC (-0.012 / -0.033) or
   EQUAL. The round-1 conclusion stands but is sharper: at 24m the trailing-reward rule was selecting
   the wrong signs from stale data, not failing because it counted correlated factors.

**Section 10 is unchanged.** The round-2 tables do not add an extraction: the stable set still needs
only **results P&L (revenue, PAT, operating margin), promoter holding, insider trades and prices**.
Valuation (earnings/sales yield, P/S vs sector) is computed from prices and the same P&L; sector P/S
adds only the held industry label. The 24m loss is a selection/staleness result, not evidence that
another document extraction is needed; the unmeasured factors in section 11 (ROE/ROCE, pledge, FPI,
MF, guidance) remain unmeasured for this round.

