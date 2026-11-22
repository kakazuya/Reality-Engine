# T-235 audit: are the stage-1 capital-flow cells real or construction artefacts?

Stage-1 (d037f578) reported 1,201 of 3,791 return cells passing Benjamini-Hochberg and a
short list of "survivors". Before trusting them, five of the most surprising cells were
recomputed from raw prices and re-tested against a tighter null. Audit run 22 Nov 2026 by
the stage-2 worker, from the merged stage-1 code and `truth_2026-11-04.duckdb`.

Inputs: `flow_signal.csv` reproduced by `python -m reality_engine.research.flow_signals
--out .tmp/t235/s1base --snapshot .../truth_2026-11-04.duckdb --start 2019-01-01 --end
2026-11-03` (222,964 signals; stage 1 reported 222,949, +0.007% from the newer
T-209/`shp_index` rows, no method change). All five cells reproduce to 2dp: delivery spike
down 5s n=4,408 mean +1.053%; delivery spike up 5s n=3,326 +1.080%; bad quarter 5s n=9,150
+1.165%; promoter down 20s n=1,785 +1.160%; volume spike up 250s n=70,286 +11.324%.

Method: 30 random events per cell (seed 20261122), entry at the close of `date_known`, exit
at +h sessions, total-return close minus Nifty 500 TRI. Every example is re-read from
`px_daily` (raw close, adjusted close, total-return close), the source filing or the source
delivery row. Script: `.tmp/t235/audit_cells.py`; per-event evidence:
`.tmp/t235/audit/audit_examples.csv` (150 rows); cell diagnostics:
`.tmp/t235/audit/audit_summary.csv`.

## 1. Cell diagnostics (2019-2026, stage-1 signals)

| cell | n | n stocks | mean % | NW t | stock-cluster t | overlap 30s | episodes | top-5 co. share | mean ex-top-5 | winsor-clipped | raw mean % | month-matched placebo mean % | month p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| delivery spike down, 5s | 4,408 | 876 | +1.053 | 6.75 | 3.65 | 58.2% | 2,014 | 4.64% | +1.025 | 326 (7.4%) | +0.961 | +1.327 | 1.00 |
| delivery spike up, 5s | 3,326 | 792 | +1.080 | 6.17 | 4.66 | 52.1% | 1,745 | 5.35% | +1.061 | 75 (2.3%) | +1.789 | +0.905 | 0.19 |
| bad quarter, 5s | 9,150 | 1,694 | +1.165 | 13.67 | 15.04 | 1.1% | 9,095 | 0.91% | +1.165 | 142 (1.6%) | +1.137 | +0.221 | 0.048 |
| promoter down, 20s | 1,785 | 881 | +1.160 | 2.31 | 3.39 | 2.2% | 1,825 | 2.68% | +1.179 | 21 (1.2%) | +1.212 | +0.627 | 0.048 |
| volume spike up, 250s | 70,286 | 1,974 | +11.324 | 9.56 | 10.39 | 76.5% | 27,454 | 0.74% | +11.129 | 1,015 (1.4%) | +12.100 | +16.339 | 1.00 |

`overlap 30s` is the share of firings within 30 sessions of the previous same-stock,
same-signal firing; `episodes` is the count after a 30-session cooldown. `raw mean` is the
unwinsorised signed excess; `mean` is the winsorised figure stage 1 reports. The
month-matched placebo draws 20 same-stock, same-year **and same-month** dates per event,
so it holds the stock's month fixed (the stage-1 placebo only held the year). With 20 seeds
the smallest attainable p is 0.048.

## 2. Per-cell verdict

**delivery spike down (5s): ARTEFACT - within-year timing.** The stock's own random dates in
the same month outperform the signal dates: placebo +1.327% versus observed +1.053%
(p = 1.00, all 20 month-matched draws at least as good). 58% of the firings are inside
30 sessions of the same stock's previous firing, so 4,408 rows are 2,014 episodes. The
same-stock, same-year placebo (+0.08%) was too weak: it removes the year drift but not the
fact that a stock with high delivery on down days is simply in a bad month. Stock clustering
does not explain the cell away (cluster t 3.65), but the month null does. **Do not trade it
as distribution.**

**delivery spike up (5s): UNCLEAR / not robust.** The mean is in the claimed direction and
stock-clustered (t 4.66), but it fails the month-matched null at 10% (p = 0.19) and is a
right-tail effect: median -0.31%, hit 47.4% (below half), and 75 events clipped at the
pooled 99th percentile (+27.6%) contribute +0.71pp of the +1.08% mean (raw mean +1.79%).
The typical event loses money; a minority of sharp bounces carries the average.

**bad quarter (5s): REAL.** The only cell of the five that survives every check: month-matched
p = 0.048 (the minimum resolvable with 20 seeds), stock-cluster t 15.0, overlap 1.1%, top-5
companies 0.9%, 142 of 9,150 events clipped (1.6%), raw and clipped means within 0.03pp. All
30 recomputed events reproduce the study excess exactly from the snapshot's availability
session. It is an announcement-window continuation (bad results, then another ~1.2pp of
underperformance over five sessions), not a predictive edge beyond the announcement; costs
are not modelled.

**promoter down (20s): REAL BUT MISLABELLED.** Month-matched p = 0.048, stock-cluster t 3.39,
top-5 2.7%, overlap 2.2%. The sign is the stage-1 "surprise": promoter percentage down, stock
outperforms. The filing dates are timely in 93.2% of events (lag <= 120 days; timely-only mean
+1.203% vs +1.160% overall), so the 2022 backfill is not driving the cell. The likely
mechanism is dilution (preferential issue, QIP, ESOP/allotment) rather than market selling;
the signal should be described as "promoter stake fell", not "promoter sold".

**volume spike up (250s): ARTEFACT - state/market beta.** Same-month random dates return
+16.34% versus the signal's +11.32% (p = 1.00). The positive raw mean is the stock's own
drift during the high-volume state, not an edge: relative to random same-month dates the
signal loses 5pp. 76.5% of the 70,286 rows are repeat firings (27,454 episodes); the 250s
measurement also overlaps heavily. Stage 1 already called this a fade against the same-year
null; the month-matched null confirms it.

## 3. Recomputed examples (4 of 150; all rows in `audit_examples.csv`)

| cell | company | date_known | entry raw close | adjusted close | exit | stock % | Nifty 500 % | excess % | study signed % | note |
|---|---|---|---:|---:|---|---:|---:|---:|---:|---|
| delivery spike down | INE659A | 2020-11-18 | 452.80 | 452.80 | 2020-11-25 | -0.85 | -0.12 | -0.74 | -0.74 | dp 76.6 vs median 36.6, ratio 2.10, day -0.3% |
| delivery spike down | INE452O | 2020-03-23 | 169.20 | 169.20 | 2020-03-30 | -26.63 | +8.15 | -34.78 | -18.26 | 1st-percentile winsorisation, not a data error |
| delivery spike up | INE932X | 2020-12-31 | 180.15 | 35.73 | 2021-01-07 | +11.38 | +2.15 | +9.23 | +9.23 | split after entry absorbed by adj_close |
| delivery spike up | INE450D | 2021-06-02 | 109.05 | 109.05 | 2021-06-09 | -3.81 | +0.94 | -4.74 | -4.74 | dp 2.87x median, up day |
| bad quarter | INE871H | 2026-04-16 | 15.74 | 15.74 | 2026-04-23 | -1.02 | +0.68 | -1.70 | +1.70 | bad-results continuation |
| bad quarter | INE393P | 2021-02-05 | 706.65 | 706.65 | 2021-02-12 | -5.96 | +1.90 | -7.86 | +7.86 | bad-results continuation |
| promoter down | INE999K | 2023-01-23 | 10.80 | 9.20 | 2023-02-21 | -22.69 | -3.10 | -19.59 | +19.59 | filing lag 11 days |
| volume spike up | INE510A | 2024-04-29 | 238.50 | 238.50 | 2025-05-02 | -24.87 | +5.86 | -30.73 | -30.73 | 1.9x volume; no corp action |

Recomputation agreed with the study for 146 of 150 examples to 1e-9; the four exceptions are
exactly the winsorised tail values (three delivery-spike-down 5s events clipped at -18.26%,
one volume-spike 250s event clipped by 0.19pp). No example had a corporate-action jump inside
a 5/20-session window; 15 of the 30 volume-spike 250-session windows contain an action, all
absorbed by the total-return close.

## 4. Cross-checks

- **Look-ahead.** Every one of the 90 market-signal examples had `date_known` equal to the
  next NSE session after the observation session, and the observation's adjusted-close sign
  matched the signal direction (30/30 per cell). Every filing-signal example's excess
  reproduced exactly. No look-ahead was found in `date_known`.
- **Survivorship.** 764 of 6,265 price entities stop trading before 2026-10; they carry 2,764
  of the 103,494 events in the five audited cells (2.7%). Delisted names are in the sample,
  not dropped.
- **Winsorisation.** The pooled 1st/99th percentile clip is applied once per horizon before
  any cell. It changes delivery-spike-up 5s by +0.71pp (toward the mean) and
  delivery-spike-down 5s by +0.09pp; bad quarter by -0.03pp. The means are clipped means, and
  delivery-spike-up depends on the clipped right tail.
- **Placebo design.** Same-stock, same-year dates remove stock and year drift but not
  within-year clustering. Adding the same-month condition removes 1 of the 4 non-bad-quarter
  survivors (delivery spike down) and leaves delivery spike up at p=0.19. It is now a second
  placebo in `flow_events.py` (`placebo_*_month` columns).
- **Overlapping events.** Stage 1 applied no cooldown to market signals, so a delivery-%
  state that persisted for weeks produced one "event" per session; 52-77% of market-signal
  rows are within 30 sessions of the previous same-stock firing. The fixed code fires each
  company/signal at most once per 30 sessions.
- **One-stock dominance.** Top-5 company share is at most 5.35% and the mean excluding the
  top five companies moves by at most 0.2pp; no cell is one small cap.
- **Newey-West lags.** Stock-clustered t is similar to or larger than the NW t in all five
  cells (3.39-15.04), so the NW t is not inflated by stock-level dependence. The overlap, not
  the standard error, was the problem.
- **Stale filings.** 3,750 `shp_index` rows carry the 2022 backfill crawl date and 1,952 of
  those have a quarter end before 2021-10. They were handled two ways: the prev-quarter-gap
  rule already dropped most, and the new 120-day freshness rule drops the rest (6.8% of
  promoter-down events; timely-only mean +1.203%).

## 5. What stage 1 got wrong, and what was changed

| artefact | evidence | fix | test |
|---|---|---|---|
| Market signals had no cooldown | 58%/52%/77% within-30-session repeats; delivery trend 17k/45k "events" were state-days | `market_events()` applies `apply_cooldown(company, signal, 30)` like insider/deal signals | `test_market_signals_apply_the_cooldown_to_state_firings` |
| Same-year placebo hides within-year timing | delivery spike down fails same-month null at p=1.00 | `flow_events.placebo_frame(..., match_month=True)`; `placebo_mean_month/diff_month/p_month/seeds_month` added to `after_signal.csv` | `test_month_matched_placebo_stays_in_the_event_month` |
| Stale shareholding filings fire on the 2022 crawl date | 1,952 rows known 2022-01-06/07 with quarter_end < 2021-10; 6.8% of promoter-down events | `_quarterly_changes()` drops filings known >120 days after their quarter end | `test_stale_shareholding_filing_does_not_fire` |
| Pre-2017 size cells were `unknown` | `results_key` starts 2017-06, so market cap is absent before 2019 | by_group drops the `size=unknown` cells instead of duplicating the signal cell | data-dependent; asserted by the empty-cell guard |
| 2010-2018 penny-tick "splits" | a Rs 0.10 stock moving to Rs 0.15 matches the 3/2 clean ratio; 1,937 false inferred actions compounded to a 1e70 factor | inferred jumps require prev close >= Rs 5 and one per 120 days; non-equity (INF) ISINs get no entity | builder report: 60 inferred, 73 residual >2x moves in 3.28M rows |

After the fixes, the 2019+ signal table shrinks from 222,964 to 89,801 rows: market signals
187,555 -> 54,862 (cooldown), promoter 2,974 -> 2,729 and FPI/MF/insurance 9,593 -> 9,292
(freshness); insider/pledge 4,649, bulk/block 2,246 and earnings 16,029 are unchanged. The
full re-run over 2010-2026 is in `docs/research/T-235_capital_flow.md` section 10.

## 6. Limits of this audit

- 30 random events per cell, not all events; the cell-level statistics use every event.
- The month-matched placebo is a stricter, ex-post conditioning; a real signal that fires in
  bad months can still be useful if it fires before the move. What it rules out is the claim
  that the signal adds information beyond "this stock is having a bad month".
- The 2010-2018 panel is NSE-only: the live BSE table has no ISIN on any row and its delivery
  column is corrupt (24-42% of rows exactly 100%). 112 of the 1,665 NSE symbols present in
  2010-2011 never reappear in 2012+, and their ~43k rows (1.3% of 2010-2018) are dropped
  because there is no ISIN to anchor them. That is a small survivorship hole in 2010-2011
  only.
- No costs, borrow or impact model; this is a data audit, not a backtest of a trading rule.
