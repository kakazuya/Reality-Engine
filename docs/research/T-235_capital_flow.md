# T-235: capital-flow early-warning signals and what followed them

Stage 1 of T-235 (Shivam, 22 Nov 2026), run 22 Nov 2026 by a dsh worker. It turns the held
market, ownership and filing data into a dated per-stock signal table and measures what
followed each signal: forward excess return versus the Nifty 500 TRI and versus the same
stock's own random dates, by size, sector, year and market phase, plus a look-back from
every +/-30% excess move and same-direction signal pairs. Delisted companies stay in.

Stage 2 (22 Nov, independent check) audited the five most surprising cells from raw prices
(`docs/research/T-235_audit.md`): two of them (delivery spike down at 5 sessions, volume
spike up at 250) are within-year timing artefacts that the stage-1 same-year placebo did not
remove; delivery spike up is a right-tail effect, bad quarter is real, promoter down is real
but means dilution, not selling. Stage 2 fixed the market-signal cooldown, the stale
shareholding filings and the placebo (a same-month null is now reported), extended the price
panel to 2010 through `reality_engine/scripts/build_flow_snapshot.py`, and reran the study
over 2010-2026. Section 10 is the round-2 result; sections 1-8 are the stage-1 record.

Code `reality_engine/research/flow_signals.py` (signals),
`reality_engine/research/flow_events.py` (study) and
`reality_engine/scripts/build_flow_snapshot.py` (2010-2018 extension); tests
`reality_engine/tests/test_flow_signals.py` (16 passed). Read-only input
`truth_2026-11-04.duckdb` plus the extended snapshot `.tmp/t235/snap_ext.duckdb` (prices
2010-01-04..2026-11-03); outputs only under `--out`:

```bash
python -m reality_engine.scripts.build_flow_snapshot --out .tmp/t235/snap_ext.duckdb  # ~6 min
python -m reality_engine.research.flow_signals --out .tmp/t235 --snapshot .tmp/t235/snap_ext.duckdb --start 2010-01-01   # ~13 min
python -m reality_engine.research.flow_events  --out .tmp/t235 --signals .tmp/t235/flow_signal.csv --snapshot .tmp/t235/snap_ext.duckdb --start 2010-01-01   # ~35 min
```

The 2019+ rerun uses the base snapshot and `--start 2019-01-01`; the availability rule, the
output schema and every threshold stay the same.

## 1. What was built (stage 1; stage-2 counts in §10)

`flow_signal(company, date_known, signal, direction, strength, detail)`: 222,949
dated observations over 3,090 companies, 2019-01-02 to 2026-11-03. Stage 2's cooldown and
filing-freshness rules cut this to 89,801 rows over the same window (129,298 over 2010-2026);
those are the counts to use.
`company` is the issuer entity code (the permanent ISIN issuer anchor of T-118/T-207), so a
symbol or ISIN change does not split a series. `strength` is a ratio, crore value or
percentage points depending on the signal; `detail` is a compact JSON with the measure.

## 2. Data, point in time and coverage

| input | use | held coverage |
|---|---|---|
| `px_daily` | raw and total-return close, volume, traded value (NSE row preferred) | 2019-01-01 to 2026-11-03 in the base snapshot; the extended snapshot adds 2010-01-04..2018-12-31, 3.28M NSE rows over 2,085 entities |
| `px_nse` | NSE delivery % only | 2019-01-01+ in the base snapshot; 2010-01-04..2018-12-31 added |
| `mkt_nse_eq_daily` / `mkt_nse_full_daily` | the 2010-2018 NSE bhavcopy behind the extension | 2010-01-04..2021-10-29 old format (ISIN null before 2012), 2019-06.. new format |
| `mkt_nse_deals` / `mkt_bse_deals` | 2010-2018 bulk/block rows (no PIT timestamp in the live table) | 2010-01-04..2026-11-03; the extension stamps a deal known after that day's close |
| `mkt_nse_insider` | 2015-11..2018 insider/pledge rows | 2015-11 onwards; extension uses `disseminated_at` (IST -> UTC) as `known_at` |
| `mkt_bse_delivery_daily` | **not used**: 24-42% of 2010-2018 rows are exactly 100% delivery | 2010-01-04..2026-11-06 |
| `mkt_bse_eq_daily` | **not used**: no ISIN on any row, so no entity anchor pre-2019 | 2010-01-04..2026-11-09 |
| `corporate_actions` | 2010-2018 split/bonus/rights/dividend parsing | 27,626 actions 2010-01-04..2026-11-04 |
| `mkt_bse_index_daily` | 2010-2018 BSE 500 price + `div_yield` -> TRI proxy | 2010-01-04..2026-11-03 |
| `nse_insider` | insider buy/sell and promoter pledge disclosures, PIT `known_at_utc` | 2019-01 to 2026-05 in the base snapshot; 2015-11..2018 added |
| `nse_deals` / `bse_deals` | named-party bulk/block flow | 2019-01 to 2026-11 in the base; 2010-2018 added |
| `shp_index` | promoter % q/q at its `known_at_utc` | 51,677 filings, 3,085 ISINs |
| `structured_universe.db` `shp_category` (T-209) | FPI / MF / insurance % q/q at broadcast time | filings since 2024-04, 3,060 ISINs |
| `results_key` | quarterly P&L, TTM availability by the 15:30 IST rule | 2017-06 to 2026-09, 106,983 filings |
| `index_tri` | Nifty 500 TRI benchmark and market phase | 2019-01-01 to 2026-10-16 official; 2010-01-04..2018-12-31 BSE 500 TRI proxy, rescaled to the Nifty 500 level on 2019-01-01 |
| `company_industry` | sector cells | 2,055 ISINs |

Point-in-time rules: a market-data signal is usable only on the **next NSE session** (the
delivery/volume print is known after the close); a filing is usable on the session selected by
the 15:30 IST rule (`factor_weights.pit_sessions`, imported not copied); shareholding is
usable from its filing/broadcast timestamp, **never the quarter end**. The calendar is built
from the snapshot's first NSE session, so a filing older than the requested window can never
collapse onto day one.

The 2010-2018 extension is NSE-only. `mkt_nse_eq_daily` carries no ISIN for 2010-2011, so
those rows are mapped by symbol to the earliest observed 2012+ ISIN window; 112 of the 1,665
symbols present in 2010-2011 never reappear and their ~43k rows (1.3% of 2010-2018) are
dropped. Non-equity ISINs (`INF...`, ETF/fund units) are excluded. Prices are adjusted with
`corporate_actions` plus inferred clean-ratio jumps only above Rs 5 (below that a 5-paise
tick is a 33-100% move; the unguarded rule produced 1,937 false actions and a 1e70 factor).
The splice at 2019-01-01 carries the base snapshot's cumulative factor for each entity and
leaves 1 of 1,736 entities with a >2x seam jump.

Not held, and therefore not built: per-stock FPI/MF/insurance categories before 2024-04 (the
snapshot's `shp_index` carries only promoter/public %, the parsed category store starts
2024-04); BSE insider disclosures as PIT rows (`bse_insider.known_at_utc` is null for all
153,904 rows, so only NSE PIT rows are used); promoter pledge **percentage** history before
2024-04 (pledge *events* from `nse_insider` cover 2019+); BSE's delivery column in `px_daily`
(average 88%, 100% on Rs 100 turnover: unusable, so delivery signals are NSE-only);
market-level FII/DII flows (`mkt_fii_dii_cash`, `mkt_nsdl_fpi_daily`) are not per-stock and
are used only as context, not as signals.

## 3. Signals and fixed thresholds

Every threshold below was set before any outcome was looked at.

| signal | rule | direction |
|---|---|---|
| delivery spike up/down | NSE delivery % >= 2x its own prior-60-session median, >= 40% level, median >= 20%; `up` when the session's adjusted-close return >= 0, else `down` | accumulation up, distribution down |
| delivery trend up/down | mean delivery % of the last 20 sessions >= 1.5x (or <= 1/1.5) the 60 sessions before them, base >= 30% | up / down |
| volume spike up/down | volume >= 3x the prior-200-session mean, prior-60-session median traded value >= Rs 1 crore, day value >= Rs 1 crore; direction by the session return | up / down |
| insider buy/sell cluster | trailing-30-day net promoter/director/KMP/relative insider value >= Rs 5 crore over >= 2 disclosures (designated-employee ESOP rows excluded) | buy up, sell down |
| pledge increase / release | trailing-30-day promoter (`person_category` contains PROMOTER) Pledge + Pledge Invoke / Pledge Revoke value >= Rs 5 crore | increase down, release up |
| bulk/block institutional buy/sell | one session's net FII + MF + insurance bulk/block value >= Rs 5 crore, parties classified by name rule | buy up, sell down |
| promoter up/down | promoter % change q/q >= 0.5pp at the filing's own availability session | up / down |
| bad quarter | TTM PAT YoY <= -25% or TTM operating margin -3pp YoY, at the 8-quarter availability session | down |
| peak quarter | TTM PAT or TTM operating margin at its own 20-quarter high (min 12 quarters), at the TTM availability session | down (peak trap) |
| FPI/MF/insurance up/down | category % change q/q >= 0.5pp at the filing's broadcast session (2024-04+) | up / down |

Every company/signal fires at most once per 30 sessions (`apply_cooldown`), so a delivery-%
state that persists for weeks is one event, not one event per session. A shareholding filing is
used only when it was published within 120 days of its quarter end: `shp_index.known_at` for
old quarters is the 2022 backfill crawl date, and without this rule 3,750 rows fire on a
handful of 2022 sessions. Both rules were added in stage 2 (`docs/research/T-235_audit.md`).

The name rule for deal parties, in order: insurance (INSURANCE, LIFE INSUR, GENERAL INSUR,
LIC OF INDIA), then mutual fund (MUTUAL FUND, ASSET MANAGEMENT, ASSET MANAGERS, AMC, MF
LTD), then foreign/institutional (FII, FPI, FOREIGN, MAURITIUS, SINGAPORE, LUXEMBOURG,
CAYMAN, BERMUDA, GLOBAL FUND, MASTER FUND, EMERGING MARKET, ETF, ISHARES, NORGES, GOLDMAN,
MORGAN STANLEY, CITIGROUP, CITADEL, UBS, NOMURA, BNP PARIBAS, JPMORGAN, HSBC, ABERDEEN,
WELLINGTON, VANGUARD, BLACKROCK, SOCIETE GENERALE, MACQUARIE); everything else is `other`
and never counts as an institutional flow.

| signal | direction | firings | companies | first | last |
|---|---|---:|---:|---|---|
| delivery spike up | up | 3,509 | 801 | 2019-02-27 | 2026-11-03 |
| delivery spike down | down | 4,574 | 883 | 2019-02-27 | 2026-11-03 |
| delivery trend up | up | 17,437 | 1,388 | 2019-01-31 | 2026-11-03 |
| delivery trend down | down | 44,635 | 1,984 | 2019-01-31 | 2026-11-03 |
| volume spike up | up | 84,964 | 2,194 | 2019-08-09 | 2026-11-03 |
| volume spike down | down | 32,436 | 2,106 | 2019-08-09 | 2026-11-03 |
| insider buy cluster | up | 1,328 | 606 | 2019-01-03 | 2026-05-04 |
| insider sell cluster | down | 1,272 | 551 | 2019-01-03 | 2026-05-04 |
| pledge increase | down | 1,182 | 286 | 2019-01-03 | 2026-04-27 |
| pledge release | up | 852 | 222 | 2019-01-02 | 2026-04-17 |
| bulk/block inst buy | up | 1,387 | 708 | 2019-01-04 | 2026-10-29 |
| bulk/block inst sell | down | 859 | 522 | 2019-01-21 | 2026-10-16 |
| promoter up | up | 970 | 591 | 2022-01-07 | 2026-10-26 |
| promoter down | down | 1,962 | 951 | 2022-01-07 | 2026-10-28 |
| bad quarter | down | 9,489 | 1,729 | 2020-08-11 | 2026-10-16 |
| peak quarter | down | 6,540 | 1,289 | 2022-02-15 | 2026-10-19 |
| FPI up | up | 1,966 | 1,038 | 2024-07-05 | 2026-10-29 |
| FPI down | down | 2,851 | 1,279 | 2024-07-10 | 2026-10-27 |
| MF up | up | 2,161 | 791 | 2024-07-05 | 2026-10-27 |
| MF down | down | 1,478 | 729 | 2024-07-11 | 2026-11-03 |
| insurance up | up | 543 | 304 | 2024-09-12 | 2026-10-26 |
| insurance down | down | 554 | 348 | 2024-07-16 | 2026-10-27 |
| **total** | | **222,949** | **3,090** | **2019-01-02** | **2026-11-03** |

## 4. After-signal method

Entry is the close of `date_known`; return is the total-return close ratio minus the Nifty 500
TRI ratio over 5 / 20 / 60 / 120 / 250 *sessions* (join on session index + h, never padded).
`mean`, `median`, `hit` and the signed excess use the signal's claimed direction (a `down`
signal's underperformance is a positive observation). Newey-West t uses horizon-1 lags; its
two-sided normal p and Benjamini-Hochberg at 10% are computed over **every** return cell
written (stage 1: after-signal, group, year and pair cells = 3,791 cells, 1,201 BH passes;
round 2 with the crossed phase and the longer sample = 4,622 cells, 1,251 BH passes, §10). A
cell needs 20 events. Each horizon is winsorised once at the pooled 1st/99th percentile over
all entity-day returns *before* any cell, so one bad corporate-action adjustment cannot move a
mean (this mattered: unwinsorised 250-session means ran to four digits). `n_stocks` and, in
round 2, the same-month placebo are reported beside every cell.

The placebo draws 20 random sessions for every event **from the same stock and the same
calendar year** (replacement, only sessions with a valid forward outcome); `placebo` is the
mean signed excess over those seeds, `placebo p` is `(1 + #{seed mean >= observed}) / 21`.
This holds the market regime fixed, so the placebo answers "did the signal beat an arbitrary
day for this stock in this year", not "did the stock go up".

Stage 2 adds a second, tighter null: 20 random sessions from the same stock, same year **and
same calendar month** (`placebo_mean_month/diff_month/p_month/seeds_month` in `after_signal.csv`). It answers
"did the signal beat an arbitrary day in the month it fired in". The audit showed this
matters: delivery spike down at 5 sessions has a same-year placebo of +0.08% but a same-month
placebo of +1.33%, i.e. it only picks bad months for the stock. With 20 seeds the smallest
attainable p is 0.048.

## 5. What followed each signal

**Stage-1 results (before the stage-2 audit).** All 110 signal x horizon cells, with counts
behind every percentage:

| signal | dir | h | n | mean % | median % | hit | NW t | placebo % | diff pp | placebo p | q(BH) | BH |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--:|
| delivery spike up | up | 5 | 3,326 | +1.08 | -0.31 | 47.4% | 6.12 | +0.28 | +0.80 | 0.048 | 2.16e-08 | yes |
| delivery spike up | up | 20 | 3,297 | +1.22 | -0.97 | 46.0% | 2.68 | +1.19 | +0.03 | 0.476 | 3.21e-02 | yes |
| delivery spike up | up | 60 | 3,210 | +2.62 | -1.73 | 47.0% | 2.26 | +3.74 | -1.12 | 1.000 | 7.87e-02 | yes |
| delivery spike up | up | 120 | 3,129 | +7.47 | -2.11 | 47.1% | 2.97 | +8.93 | -1.46 | 0.952 | 1.53e-02 | yes |
| delivery spike up | up | 250 | 2,964 | +23.60 | -0.96 | 48.8% | 3.37 | +23.85 | -0.25 | 0.619 | 4.77e-03 | yes |
| delivery spike down | down | 5 | 4,408 | +1.05 | +0.75 | 56.4% | 6.88 | +0.08 | +0.97 | 0.048 | 1.89e-10 | yes |
| delivery spike down | down | 20 | 4,356 | +0.23 | +1.19 | 54.6% | 0.49 | +0.01 | +0.22 | 0.190 | 7.66e-01 | no |
| delivery spike down | down | 60 | 4,213 | +0.40 | +3.50 | 56.4% | 0.31 | -0.25 | +0.66 | 0.143 | 8.62e-01 | no |
| delivery spike down | down | 120 | 4,127 | -2.21 | +4.90 | 55.9% | -0.94 | -1.39 | -0.81 | 1.000 | 5.39e-01 | no |
| delivery spike down | down | 250 | 3,858 | -11.17 | +5.93 | 55.5% | -2.27 | -8.90 | -2.28 | 1.000 | 7.70e-02 | yes |
| delivery trend up | up | 5 | 16,785 | +0.19 | -0.76 | 44.6% | 2.33 | +0.15 | +0.04 | 0.238 | 6.92e-02 | yes |
| delivery trend up | up | 20 | 16,539 | +0.45 | -1.75 | 43.6% | 1.84 | +0.72 | -0.27 | 1.000 | 1.75e-01 | no |
| delivery trend up | up | 60 | 15,772 | +2.54 | -2.87 | 44.6% | 3.31 | +2.02 | +0.52 | 0.048 | 5.72e-03 | yes |
| delivery trend up | up | 120 | 15,143 | +4.86 | -5.89 | 42.8% | 3.16 | +5.12 | -0.26 | 0.857 | 8.91e-03 | yes |
| delivery trend up | up | 250 | 14,107 | +20.22 | -6.35 | 45.9% | 4.94 | +18.31 | +1.91 | 0.048 | 1.03e-05 | yes |
| delivery trend down | down | 5 | 43,535 | +0.15 | +0.84 | 56.8% | 4.04 | -0.39 | +0.54 | 0.048 | 4.85e-04 | yes |
| delivery trend down | down | 20 | 42,887 | -0.06 | +1.90 | 57.4% | -0.49 | -1.62 | +1.56 | 0.048 | 7.66e-01 | no |
| delivery trend down | down | 60 | 41,567 | -0.92 | +3.99 | 58.2% | -2.59 | -4.75 | +3.83 | 0.048 | 3.96e-02 | yes |
| delivery trend down | down | 120 | 39,353 | -2.84 | +6.45 | 58.5% | -3.71 | -9.39 | +6.55 | 0.048 | 1.60e-03 | yes |
| delivery trend down | down | 250 | 35,082 | -14.65 | +7.50 | 56.2% | -6.26 | -20.59 | +5.94 | 0.048 | 9.67e-09 | yes |
| volume spike up | up | 5 | 84,316 | -0.09 | -0.98 | 42.7% | -3.03 | +0.46 | -0.55 | 1.000 | 1.33e-02 | yes |
| volume spike up | up | 20 | 83,468 | +0.44 | -1.57 | 44.2% | 5.72 | +1.93 | -1.49 | 1.000 | 2.04e-07 | yes |
| volume spike up | up | 60 | 80,840 | +1.34 | -2.89 | 44.3% | 6.35 | +5.83 | -4.49 | 1.000 | 5.51e-09 | yes |
| volume spike up | up | 120 | 76,374 | +3.33 | -4.13 | 44.5% | 7.59 | +11.35 | -8.02 | 1.000 | 1.42e-12 | yes |
| volume spike up | up | 250 | 70,286 | +11.32 | -5.60 | 45.3% | 9.55 | +21.17 | -9.84 | 1.000 | 1.02e-19 | yes |
| volume spike down | down | 5 | 32,062 | +0.01 | +0.67 | 55.2% | 0.21 | -0.22 | +0.23 | 0.048 | 9.09e-01 | no |
| volume spike down | down | 20 | 31,693 | -0.21 | +1.37 | 55.5% | -1.61 | -0.98 | +0.78 | 0.048 | 2.49e-01 | no |
| volume spike down | down | 60 | 30,569 | -0.42 | +3.00 | 56.1% | -1.22 | -3.08 | +2.67 | 0.048 | 4.04e-01 | no |
| volume spike down | down | 120 | 28,750 | -1.60 | +5.22 | 57.1% | -2.31 | -6.10 | +4.50 | 0.048 | 7.16e-02 | yes |
| volume spike down | down | 250 | 25,727 | -5.79 | +9.08 | 58.0% | -3.22 | -12.12 | +6.32 | 0.048 | 7.55e-03 | yes |
| insider buy cluster | up | 5 | 1,318 | +0.65 | -0.02 | 49.8% | 3.19 | +0.27 | +0.38 | 0.048 | 8.25e-03 | yes |
| insider buy cluster | up | 20 | 1,315 | +1.49 | -0.58 | 47.7% | 3.05 | +1.25 | +0.24 | 0.238 | 1.24e-02 | yes |
| insider buy cluster | up | 60 | 1,312 | +3.87 | +0.03 | 50.2% | 2.59 | +3.53 | +0.34 | 0.286 | 3.96e-02 | yes |
| insider buy cluster | up | 120 | 1,311 | +7.83 | -0.50 | 48.9% | 2.37 | +8.56 | -0.73 | 0.762 | 6.31e-02 | yes |
| insider buy cluster | up | 250 | 1,198 | +19.22 | -0.80 | 48.9% | 2.42 | +20.90 | -1.68 | 0.952 | 5.69e-02 | yes |
| insider sell cluster | down | 5 | 1,268 | +0.02 | +0.41 | 54.6% | 0.09 | -0.25 | +0.26 | 0.095 | 9.63e-01 | no |
| insider sell cluster | down | 20 | 1,266 | -0.62 | +0.87 | 54.3% | -1.38 | -1.10 | +0.48 | 0.095 | 3.36e-01 | no |
| insider sell cluster | down | 60 | 1,262 | -0.23 | +2.31 | 56.5% | -0.22 | -2.61 | +2.38 | 0.048 | 9.08e-01 | no |
| insider sell cluster | down | 120 | 1,259 | -0.17 | +3.56 | 57.4% | -0.10 | -5.63 | +5.46 | 0.048 | 9.59e-01 | no |
| insider sell cluster | down | 250 | 1,212 | -4.69 | +7.54 | 58.1% | -1.28 | -10.03 | +5.34 | 0.048 | 3.78e-01 | no |
| pledge increase | down | 5 | 1,176 | +0.29 | +0.67 | 55.0% | 1.27 | +0.06 | +0.23 | 0.190 | 3.83e-01 | no |
| pledge increase | down | 20 | 1,176 | +0.09 | +1.17 | 54.8% | 0.13 | -0.03 | +0.11 | 0.476 | 9.50e-01 | no |
| pledge increase | down | 60 | 1,175 | +0.24 | +3.35 | 57.0% | 0.12 | +0.53 | -0.29 | 0.619 | 9.52e-01 | no |
| pledge increase | down | 120 | 1,165 | -2.40 | +5.03 | 55.6% | -0.61 | -1.07 | -1.33 | 0.952 | 7.07e-01 | no |
| pledge increase | down | 250 | 1,104 | -9.95 | +5.32 | 55.4% | -1.29 | -11.45 | +1.49 | 0.143 | 3.75e-01 | no |
| pledge release | up | 5 | 848 | +0.01 | -0.50 | 45.3% | 0.03 | +0.20 | -0.19 | 0.762 | 9.87e-01 | no |
| pledge release | up | 20 | 849 | +1.15 | -0.93 | 46.4% | 1.63 | +0.91 | +0.24 | 0.381 | 2.46e-01 | no |
| pledge release | up | 60 | 847 | +2.29 | -1.57 | 47.7% | 1.13 | +2.66 | -0.37 | 0.667 | 4.48e-01 | no |
| pledge release | up | 120 | 847 | +5.70 | -4.35 | 44.2% | 1.12 | +7.18 | -1.48 | 0.857 | 4.53e-01 | no |
| pledge release | up | 250 | 813 | +19.94 | -1.35 | 49.2% | 1.91 | +21.74 | -1.80 | 0.952 | 1.57e-01 | no |
| bulk/block inst buy | up | 5 | 1,373 | -0.05 | -0.75 | 43.5% | -0.26 | +0.34 | -0.39 | 0.952 | 8.86e-01 | no |
| bulk/block inst buy | up | 20 | 1,338 | +0.77 | -0.01 | 49.9% | 1.68 | +1.25 | -0.49 | 0.952 | 2.26e-01 | no |
| bulk/block inst buy | up | 60 | 1,260 | +1.30 | -0.68 | 48.3% | 1.24 | +3.22 | -1.93 | 1.000 | 3.96e-01 | no |
| bulk/block inst buy | up | 120 | 1,193 | +2.76 | -2.50 | 47.7% | 1.12 | +6.35 | -3.58 | 1.000 | 4.54e-01 | no |
| bulk/block inst buy | up | 250 | 1,066 | +4.80 | -4.44 | 46.2% | 1.39 | +11.54 | -6.74 | 1.000 | 3.29e-01 | no |
| bulk/block inst sell | down | 5 | 849 | -0.81 | -0.11 | 48.6% | -2.83 | -0.09 | -0.71 | 1.000 | 2.17e-02 | yes |
| bulk/block inst sell | down | 20 | 837 | -1.35 | +0.09 | 50.3% | -1.88 | -0.61 | -0.75 | 1.000 | 1.65e-01 | no |
| bulk/block inst sell | down | 60 | 801 | -2.21 | +0.27 | 50.7% | -1.31 | -1.64 | -0.57 | 0.762 | 3.65e-01 | no |
| bulk/block inst sell | down | 120 | 774 | -3.56 | +3.43 | 55.6% | -1.05 | -4.64 | +1.07 | 0.143 | 4.86e-01 | no |
| bulk/block inst sell | down | 250 | 700 | -6.77 | +6.78 | 56.9% | -1.05 | -9.16 | +2.38 | 0.095 | 4.86e-01 | no |
| promoter up | up | 5 | 870 | +0.66 | -0.41 | 47.1% | 2.97 | +0.22 | +0.44 | 0.048 | 1.52e-02 | yes |
| promoter up | up | 20 | 854 | +0.96 | -1.47 | 44.7% | 1.55 | +1.16 | -0.20 | 0.667 | 2.68e-01 | no |
| promoter up | up | 60 | 834 | +3.34 | -0.61 | 48.4% | 3.13 | +2.89 | +0.45 | 0.190 | 9.89e-03 | yes |
| promoter up | up | 120 | 773 | +4.84 | -3.64 | 46.1% | 1.83 | +4.51 | +0.32 | 0.429 | 1.77e-01 | no |
| promoter up | up | 250 | 588 | +8.23 | -6.01 | 44.2% | 1.10 | +8.86 | -0.62 | 0.619 | 4.63e-01 | no |
| promoter down | down | 5 | 1,812 | +0.41 | +0.92 | 58.1% | 2.40 | -0.08 | +0.50 | 0.048 | 5.84e-02 | yes |
| promoter down | down | 20 | 1,785 | +1.16 | +2.51 | 59.7% | 2.28 | -0.20 | +1.36 | 0.048 | 7.60e-02 | yes |
| promoter down | down | 60 | 1,743 | +0.95 | +4.61 | 59.6% | 0.72 | -0.61 | +1.56 | 0.048 | 6.47e-01 | no |
| promoter down | down | 120 | 1,648 | +2.18 | +8.49 | 61.9% | 0.90 | -0.99 | +3.17 | 0.048 | 5.57e-01 | no |
| promoter down | down | 250 | 1,416 | +4.34 | +17.70 | 64.6% | 0.91 | -0.49 | +4.84 | 0.048 | 5.51e-01 | no |
| bad quarter | down | 5 | 9,150 | +1.16 | +1.83 | 64.2% | 13.64 | -0.02 | +1.19 | 0.048 | 6.60e-40 | yes |
| bad quarter | down | 20 | 9,107 | +0.00 | +2.25 | 59.2% | 0.00 | -0.16 | +0.16 | 0.190 | 9.98e-01 | no |
| bad quarter | down | 60 | 8,574 | -0.59 | +3.25 | 57.8% | -0.94 | -0.74 | +0.15 | 0.190 | 5.39e-01 | no |
| bad quarter | down | 120 | 8,082 | -3.60 | +4.80 | 57.5% | -2.34 | -2.37 | -1.23 | 1.000 | 6.71e-02 | yes |
| bad quarter | down | 250 | 7,002 | -9.50 | +8.11 | 57.9% | -2.40 | -8.29 | -1.21 | 1.000 | 5.89e-02 | yes |
| peak quarter | down | 5 | 6,414 | -0.15 | +0.67 | 55.6% | -1.70 | -0.42 | +0.27 | 0.048 | 2.18e-01 | no |
| peak quarter | down | 20 | 6,402 | -1.36 | +0.58 | 52.3% | -5.61 | -1.74 | +0.38 | 0.048 | 3.76e-07 | yes |
| peak quarter | down | 60 | 5,940 | -3.81 | +0.06 | 50.2% | -5.99 | -4.66 | +0.85 | 0.048 | 4.50e-08 | yes |
| peak quarter | down | 120 | 5,443 | -6.40 | +0.89 | 51.3% | -4.04 | -8.80 | +2.41 | 0.048 | 4.82e-04 | yes |
| peak quarter | down | 250 | 4,592 | -11.85 | +3.32 | 53.5% | -2.97 | -15.08 | +3.23 | 0.048 | 1.52e-02 | yes |
| FPI up | up | 5 | 1,718 | -0.48 | -0.75 | 42.2% | -2.91 | +0.25 | -0.73 | 1.000 | 1.77e-02 | yes |
| FPI up | up | 20 | 1,686 | -0.54 | -1.75 | 42.1% | -1.17 | +1.12 | -1.66 | 1.000 | 4.29e-01 | no |
| FPI up | up | 60 | 1,656 | +0.41 | -2.44 | 43.1% | 0.35 | +4.16 | -3.75 | 1.000 | 8.42e-01 | no |
| FPI up | up | 120 | 1,414 | -0.98 | -4.90 | 40.5% | -0.46 | +5.56 | -6.54 | 1.000 | 7.82e-01 | no |
| FPI up | up | 250 | 909 | -5.71 | -12.45 | 34.4% | -1.45 | +3.77 | -9.49 | 1.000 | 3.08e-01 | no |
| FPI down | down | 5 | 2,553 | +0.41 | +0.67 | 57.4% | 3.35 | +0.06 | +0.34 | 0.048 | 5.21e-03 | yes |
| FPI down | down | 20 | 2,501 | +0.25 | +1.34 | 56.2% | 0.70 | +0.15 | +0.10 | 0.333 | 6.58e-01 | no |
| FPI down | down | 60 | 2,444 | -0.67 | +2.09 | 55.6% | -0.68 | -0.26 | -0.41 | 0.952 | 6.69e-01 | no |
| FPI down | down | 120 | 2,093 | -1.13 | +3.77 | 56.5% | -0.53 | -1.84 | +0.72 | 0.048 | 7.48e-01 | no |
| FPI down | down | 250 | 1,171 | +4.01 | +11.74 | 64.6% | 1.19 | +2.10 | +1.91 | 0.048 | 4.17e-01 | no |
| MF up | up | 5 | 1,934 | -0.21 | -0.38 | 46.4% | -1.66 | +0.15 | -0.37 | 1.000 | 2.32e-01 | no |
| MF up | up | 20 | 1,895 | +0.18 | -0.75 | 45.6% | 0.52 | +0.69 | -0.52 | 1.000 | 7.52e-01 | no |
| MF up | up | 60 | 1,870 | +1.37 | -0.92 | 47.1% | 1.46 | +2.64 | -1.27 | 1.000 | 3.03e-01 | no |
| MF up | up | 120 | 1,596 | +2.33 | -2.30 | 46.0% | 1.05 | +5.13 | -2.80 | 1.000 | 4.86e-01 | no |
| MF up | up | 250 | 935 | -0.33 | -7.07 | 41.7% | -0.11 | +3.69 | -4.02 | 1.000 | 9.55e-01 | no |
| MF down | down | 5 | 1,270 | +0.26 | +0.71 | 57.7% | 1.57 | -0.10 | +0.36 | 0.048 | 2.62e-01 | no |
| MF down | down | 20 | 1,251 | -0.25 | +1.22 | 55.7% | -0.52 | -0.49 | +0.23 | 0.333 | 7.52e-01 | no |
| MF down | down | 60 | 1,233 | -2.20 | +1.36 | 54.7% | -1.51 | -2.18 | -0.02 | 0.524 | 2.83e-01 | no |
| MF down | down | 120 | 1,033 | -2.20 | +3.43 | 57.4% | -0.77 | -4.09 | +1.89 | 0.048 | 6.25e-01 | no |
| MF down | down | 250 | 598 | +2.16 | +9.97 | 63.9% | 0.68 | -0.48 | +2.65 | 0.048 | 6.66e-01 | no |
| insurance up | up | 5 | 478 | -0.12 | -0.32 | 45.4% | -0.48 | -0.05 | -0.06 | 0.571 | 7.71e-01 | no |
| insurance up | up | 20 | 472 | -0.04 | -0.91 | 44.7% | -0.06 | -0.13 | +0.10 | 0.381 | 9.76e-01 | no |
| insurance up | up | 60 | 464 | +0.04 | -1.07 | 46.6% | 0.03 | +0.22 | -0.18 | 0.571 | 9.87e-01 | no |
| insurance up | up | 120 | 393 | -0.84 | -3.44 | 44.0% | -0.56 | +0.59 | -1.43 | 1.000 | 7.33e-01 | no |
| insurance up | up | 250 | 224 | -0.80 | -6.81 | 38.4% | -0.47 | +0.67 | -1.47 | 0.952 | 7.73e-01 | no |
| insurance down | down | 5 | 476 | +0.09 | +0.37 | 55.9% | 0.34 | -0.23 | +0.32 | 0.095 | 8.46e-01 | no |
| insurance down | down | 20 | 463 | +0.28 | +1.50 | 57.2% | 0.37 | -0.75 | +1.03 | 0.048 | 8.27e-01 | no |
| insurance down | down | 60 | 454 | -1.91 | +1.30 | 54.8% | -1.04 | -2.75 | +0.85 | 0.095 | 4.88e-01 | no |
| insurance down | down | 120 | 364 | -3.02 | +3.05 | 55.8% | -0.99 | -5.11 | +2.08 | 0.095 | 5.13e-01 | no |
| insurance down | down | 250 | 257 | +0.16 | +6.88 | 58.8% | 0.04 | -2.84 | +3.00 | 0.048 | 9.82e-01 | no |

**Survivors** (claimed direction, BH pass, mean better than the same stock's random dates,
placebo p <= 0.10):

| horizon | signal | n | mean | placebo | diff | hit | NW t | placebo p |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 5 | delivery spike up | 3,326 | +1.08 | +0.28 | +0.80 | 47.4% | 6.12 | 0.048 |
| 5 | delivery spike down | 4,408 | +1.05 | +0.08 | +0.97 | 56.4% | 6.88 | 0.048 |
| 5 | delivery trend down | 43,535 | +0.15 | -0.39 | +0.54 | 56.8% | 4.04 | 0.048 |
| 5 | insider buy cluster | 1,318 | +0.65 | +0.27 | +0.38 | 49.8% | 3.19 | 0.048 |
| 5 | promoter up | 870 | +0.66 | +0.22 | +0.44 | 47.1% | 2.97 | 0.048 |
| 5 | promoter down | 1,812 | +0.41 | -0.08 | +0.50 | 58.1% | 2.40 | 0.048 |
| 5 | bad quarter | 9,150 | +1.16 | -0.02 | +1.19 | 64.2% | 13.64 | 0.048 |
| 5 | FPI down | 2,553 | +0.41 | +0.06 | +0.34 | 57.4% | 3.35 | 0.048 |
| 20 | promoter down | 1,785 | +1.16 | -0.20 | +1.36 | 59.7% | 2.28 | 0.048 |
| 60 | delivery trend up | 15,772 | +2.54 | +2.02 | +0.52 | 44.6% | 3.31 | 0.048 |
| 250 | delivery trend up | 14,107 | +20.22 | +18.31 | +1.91 | 45.9% | 4.94 | 0.048 |

Reading: those cells are the only ones that clear all three tests. Most raw means are
significant (the BH pass count is high) because of the 2023-24 small/mid-cap drift; after the
same-stock, same-year placebo almost nothing is left. The pattern is short-lived: nine
survivors are at 5 sessions, one (`promoter down`) at 20, and only `delivery trend up` at 60
and 250 -- and that last one is marginal (+2.54% mean, +0.52%
over the placebo). Several survivors are thin: `delivery spike up` and `delivery trend up` have
a positive mean but a negative median and a hit rate below 50%, so their mean is carried by the
right tail rather than by a majority of events. `bad quarter` is the broadest short-horizon
effect (+1.16% in five sessions, 64.2% hit, NW t 13.6)
and it reverses by 250 sessions. `peak quarter` does **not** underperform (the T-207 peak-trap
result does not reproduce as a raw price signal). `volume spike up` has large positive raw
returns but far below its own random-date baseline: the strength that produced the spike fades.

**Group cells.** The per-signal size, sector and phase cells are in `by_group.csv`
(2,639 cells). Summary of how many cells pass BH and how many do so in the
signal's claimed direction:

| group type | cells (n >= 20) | BH passes | claimed-direction BH passes |
|---|---:|---:|---:|
| size | 377 | 119 | 68 |
| sector | 1,823 | 449 | 261 |
| phase_200dma | 220 | 74 | 48 |
| phase_12m | 219 | 64 | 40 |

**Year by year** for the six largest 5-session survivors (all horizons are in
`by_year.csv`; `median peak h` is the median, across that year's events, of the measured
horizon where the signed excess is largest):

| signal | year | h | n | mean | hit | median peak h |
|---|---:|---:|---:|---:|---:|---:|
| delivery spike up | 2019 | 5 | 460 | +0.68 | 47.6% | 60 |
| delivery spike up | 2019 | 20 | 460 | -1.30 | 44.8% | 60 |
| delivery spike up | 2019 | 60 | 451 | -7.76 | 33.5% | 60 |
| delivery spike up | 2019 | 250 | 451 | +1.94 | 41.7% | 60 |
| delivery spike up | 2020 | 5 | 674 | +1.63 | 49.6% | 120 |
| delivery spike up | 2020 | 20 | 672 | -0.12 | 44.2% | 120 |
| delivery spike up | 2020 | 60 | 669 | +7.48 | 52.2% | 120 |
| delivery spike up | 2020 | 250 | 677 | +45.69 | 59.7% | 120 |
| delivery spike up | 2021 | 5 | 433 | +1.76 | 46.2% | 120 |
| delivery spike up | 2021 | 20 | 439 | +2.68 | 47.8% | 120 |
| delivery spike up | 2021 | 60 | 438 | +4.96 | 49.8% | 120 |
| delivery spike up | 2021 | 250 | 435 | +43.73 | 51.5% | 120 |
| delivery spike up | 2022 | 5 | 451 | +1.64 | 48.8% | 120 |
| delivery spike up | 2022 | 20 | 452 | +2.91 | 44.7% | 120 |
| delivery spike up | 2022 | 60 | 450 | +5.03 | 53.1% | 120 |
| delivery spike up | 2022 | 250 | 447 | +37.88 | 57.3% | 120 |
| delivery spike up | 2023 | 5 | 428 | +0.88 | 45.8% | 120 |
| delivery spike up | 2023 | 20 | 428 | +3.00 | 48.6% | 120 |
| delivery spike up | 2023 | 60 | 432 | +5.84 | 53.5% | 120 |
| delivery spike up | 2023 | 250 | 431 | +15.61 | 45.9% | 120 |
| delivery spike up | 2024 | 5 | 284 | +0.44 | 43.0% | 20 |
| delivery spike up | 2024 | 20 | 283 | +0.01 | 43.8% | 20 |
| delivery spike up | 2024 | 60 | 286 | -2.74 | 37.8% | 20 |
| delivery spike up | 2024 | 250 | 280 | -13.61 | 27.9% | 20 |
| delivery spike up | 2025 | 5 | 299 | +0.03 | 43.8% | 60 |
| delivery spike up | 2025 | 20 | 298 | +0.39 | 42.3% | 60 |
| delivery spike up | 2025 | 60 | 294 | -0.19 | 40.1% | 60 |
| delivery spike up | 2025 | 250 | 243 | -2.99 | 40.3% | 60 |
| delivery spike up | 2026 | 5 | 297 | +0.58 | 51.9% | 20 |
| delivery spike up | 2026 | 20 | 265 | +3.03 | 54.7% | 20 |
| delivery spike up | 2026 | 60 | 190 | +4.15 | 50.5% | 20 |
| delivery spike down | 2019 | 5 | 749 | +2.66 | 63.8% | 120 |
| delivery spike down | 2019 | 20 | 749 | +3.20 | 62.2% | 120 |
| delivery spike down | 2019 | 60 | 739 | +10.85 | 69.6% | 120 |
| delivery spike down | 2019 | 250 | 718 | +5.78 | 62.3% | 120 |
| delivery spike down | 2020 | 5 | 911 | +1.86 | 57.7% | 120 |
| delivery spike down | 2020 | 20 | 909 | +0.55 | 54.8% | 120 |
| delivery spike down | 2020 | 60 | 912 | -3.43 | 52.9% | 120 |
| delivery spike down | 2020 | 250 | 918 | -25.21 | 51.6% | 120 |
| delivery spike down | 2021 | 5 | 543 | -0.47 | 54.1% | 120 |
| delivery spike down | 2021 | 20 | 545 | -1.61 | 52.7% | 120 |
| delivery spike down | 2021 | 60 | 546 | -3.79 | 51.6% | 120 |
| delivery spike down | 2021 | 250 | 545 | -34.64 | 49.4% | 120 |
| delivery spike down | 2022 | 5 | 554 | -0.45 | 47.7% | 120 |
| delivery spike down | 2022 | 20 | 552 | -1.13 | 48.2% | 120 |
| delivery spike down | 2022 | 60 | 550 | -1.12 | 50.5% | 120 |
| delivery spike down | 2022 | 250 | 544 | -11.71 | 45.8% | 120 |
| delivery spike down | 2023 | 5 | 480 | +1.00 | 56.2% | 120 |
| delivery spike down | 2023 | 20 | 482 | -2.96 | 49.2% | 120 |
| delivery spike down | 2023 | 60 | 483 | -3.36 | 49.9% | 120 |
| delivery spike down | 2023 | 250 | 477 | -12.27 | 55.8% | 120 |
| delivery spike down | 2024 | 5 | 320 | +0.56 | 59.7% | 250 |
| delivery spike down | 2024 | 20 | 322 | +0.57 | 55.3% | 250 |
| delivery spike down | 2024 | 60 | 321 | +4.42 | 67.0% | 250 |
| delivery spike down | 2024 | 250 | 308 | +18.53 | 72.4% | 250 |
| delivery spike down | 2025 | 5 | 420 | -0.22 | 51.0% | 120 |
| delivery spike down | 2025 | 20 | 421 | +0.63 | 57.0% | 120 |
| delivery spike down | 2025 | 60 | 421 | +1.03 | 59.4% | 120 |
| delivery spike down | 2025 | 250 | 348 | +3.69 | 61.5% | 120 |
| delivery spike down | 2026 | 5 | 431 | +2.08 | 58.2% | 20 |
| delivery spike down | 2026 | 20 | 376 | +1.56 | 55.1% | 20 |
| delivery spike down | 2026 | 60 | 241 | -3.03 | 47.3% | 20 |
| insider buy cluster | 2019 | 5 | 204 | +0.14 | 45.6% | 60 |
| insider buy cluster | 2019 | 20 | 204 | -0.43 | 43.1% | 60 |
| insider buy cluster | 2019 | 60 | 204 | -3.93 | 39.2% | 60 |
| insider buy cluster | 2019 | 250 | 203 | +2.15 | 38.4% | 60 |
| insider buy cluster | 2020 | 5 | 213 | +0.41 | 49.3% | 250 |
| insider buy cluster | 2020 | 20 | 213 | +1.86 | 48.4% | 250 |
| insider buy cluster | 2020 | 60 | 213 | +9.46 | 57.3% | 250 |
| insider buy cluster | 2020 | 250 | 212 | +58.66 | 65.1% | 250 |
| insider buy cluster | 2021 | 5 | 191 | +0.87 | 49.2% | 60 |
| insider buy cluster | 2021 | 20 | 191 | +2.39 | 47.6% | 60 |
| insider buy cluster | 2021 | 60 | 191 | +8.64 | 56.0% | 60 |
| insider buy cluster | 2021 | 250 | 191 | +20.37 | 50.3% | 60 |
| insider buy cluster | 2022 | 5 | 179 | +0.28 | 49.7% | 60 |
| insider buy cluster | 2022 | 20 | 180 | +0.64 | 40.0% | 60 |
| insider buy cluster | 2022 | 60 | 179 | +1.12 | 48.0% | 60 |
| insider buy cluster | 2022 | 250 | 178 | +14.92 | 46.6% | 60 |
| insider buy cluster | 2023 | 5 | 147 | +1.01 | 47.6% | 120 |
| insider buy cluster | 2023 | 20 | 145 | +2.96 | 52.4% | 120 |
| insider buy cluster | 2023 | 60 | 145 | +6.88 | 54.5% | 120 |
| insider buy cluster | 2023 | 250 | 148 | +22.45 | 57.4% | 120 |
| insider buy cluster | 2024 | 5 | 141 | +1.67 | 60.3% | 60 |
| insider buy cluster | 2024 | 20 | 141 | +3.41 | 57.4% | 60 |
| insider buy cluster | 2024 | 60 | 140 | +2.32 | 48.6% | 60 |
| insider buy cluster | 2024 | 250 | 139 | -0.50 | 38.1% | 60 |
| insider buy cluster | 2025 | 5 | 171 | +0.35 | 48.0% | 60 |
| insider buy cluster | 2025 | 20 | 169 | -0.34 | 44.4% | 60 |
| insider buy cluster | 2025 | 60 | 168 | -0.38 | 39.3% | 60 |
| insider buy cluster | 2025 | 250 | 127 | +2.79 | 41.7% | 60 |
| insider buy cluster | 2026 | 5 | 72 | +1.21 | 52.8% | 60 |
| insider buy cluster | 2026 | 20 | 72 | +3.14 | 56.9% | 60 |
| insider buy cluster | 2026 | 60 | 72 | +10.57 | 69.4% | 60 |
| promoter up | 2022 | 5 | 165 | +0.47 | 45.5% | 60 |
| promoter up | 2022 | 20 | 164 | -1.38 | 41.5% | 60 |
| promoter up | 2022 | 60 | 161 | +2.76 | 44.1% | 60 |
| promoter up | 2022 | 250 | 161 | +10.30 | 44.1% | 60 |
| promoter up | 2023 | 5 | 153 | +0.41 | 46.4% | 120 |
| promoter up | 2023 | 20 | 151 | +0.72 | 45.7% | 120 |
| promoter up | 2023 | 60 | 149 | +5.79 | 52.3% | 120 |
| promoter up | 2023 | 250 | 150 | +29.05 | 62.0% | 120 |
| promoter up | 2024 | 5 | 142 | +1.16 | 48.6% | 60 |
| promoter up | 2024 | 20 | 142 | +2.45 | 46.5% | 60 |
| promoter up | 2024 | 60 | 142 | +1.57 | 42.3% | 60 |
| promoter up | 2024 | 250 | 140 | -0.87 | 39.3% | 60 |
| promoter up | 2025 | 5 | 178 | +0.09 | 41.6% | 20 |
| promoter up | 2025 | 20 | 176 | -0.96 | 37.5% | 20 |
| promoter up | 2025 | 60 | 178 | -1.06 | 41.6% | 20 |
| promoter up | 2025 | 250 | 137 | -7.68 | 29.9% | 20 |
| promoter up | 2026 | 5 | 232 | +1.09 | 52.2% | 60 |
| promoter up | 2026 | 20 | 221 | +3.42 | 51.1% | 60 |
| promoter up | 2026 | 60 | 204 | +7.07 | 59.3% | 60 |
| promoter down | 2022 | 5 | 268 | +1.44 | 61.6% | 185 |
| promoter down | 2022 | 20 | 268 | +4.19 | 66.0% | 185 |
| promoter down | 2022 | 60 | 266 | +5.35 | 67.7% | 185 |
| promoter down | 2022 | 250 | 254 | +5.91 | 63.8% | 185 |
| promoter down | 2023 | 5 | 366 | -0.22 | 57.7% | 120 |
| promoter down | 2023 | 20 | 366 | -1.44 | 53.6% | 120 |
| promoter down | 2023 | 60 | 359 | -5.30 | 48.2% | 120 |
| promoter down | 2023 | 250 | 360 | -13.22 | 50.8% | 120 |
| promoter down | 2024 | 5 | 481 | +0.19 | 57.0% | 250 |
| promoter down | 2024 | 20 | 480 | +0.42 | 59.0% | 250 |
| promoter down | 2024 | 60 | 480 | +1.96 | 60.2% | 250 |
| promoter down | 2024 | 250 | 475 | +13.98 | 72.8% | 250 |
| promoter down | 2025 | 5 | 409 | +1.16 | 61.6% | 120 |
| promoter down | 2025 | 20 | 411 | +3.78 | 67.9% | 120 |
| promoter down | 2025 | 60 | 407 | +6.21 | 68.8% | 120 |
| promoter down | 2025 | 250 | 327 | +8.47 | 68.5% | 120 |
| promoter down | 2026 | 5 | 288 | -0.42 | 52.1% | 20 |
| promoter down | 2026 | 20 | 260 | -1.09 | 50.4% | 20 |
| promoter down | 2026 | 60 | 231 | -5.79 | 50.2% | 20 |
| bad quarter | 2020 | 5 | 407 | -1.26 | 49.4% | 60 |
| bad quarter | 2020 | 20 | 407 | -12.17 | 29.5% | 60 |
| bad quarter | 2020 | 60 | 403 | -10.87 | 43.2% | 60 |
| bad quarter | 2020 | 250 | 399 | -58.78 | 31.3% | 60 |
| bad quarter | 2021 | 5 | 1,119 | +1.24 | 64.0% | 60 |
| bad quarter | 2021 | 20 | 1,115 | -2.32 | 54.1% | 60 |
| bad quarter | 2021 | 60 | 1,109 | -5.74 | 52.1% | 60 |
| bad quarter | 2021 | 250 | 1,098 | -27.49 | 44.6% | 60 |
| bad quarter | 2022 | 5 | 1,190 | +1.28 | 65.0% | 120 |
| bad quarter | 2022 | 20 | 1,186 | +0.07 | 58.8% | 120 |
| bad quarter | 2022 | 60 | 1,182 | +1.61 | 60.8% | 120 |
| bad quarter | 2022 | 250 | 1,156 | -3.76 | 57.2% | 120 |
| bad quarter | 2023 | 5 | 1,306 | +0.24 | 59.9% | 120 |
| bad quarter | 2023 | 20 | 1,304 | -0.99 | 52.6% | 120 |
| bad quarter | 2023 | 60 | 1,294 | -5.28 | 46.1% | 120 |
| bad quarter | 2023 | 250 | 1,282 | -24.75 | 47.6% | 120 |
| bad quarter | 2024 | 5 | 1,568 | +1.33 | 64.8% | 250 |
| bad quarter | 2024 | 20 | 1,566 | +0.71 | 61.0% | 250 |
| bad quarter | 2024 | 60 | 1,555 | -0.15 | 59.9% | 250 |
| bad quarter | 2024 | 250 | 1,534 | +6.41 | 68.9% | 250 |
| bad quarter | 2025 | 5 | 2,031 | +1.79 | 67.8% | 120 |
| bad quarter | 2025 | 20 | 2,028 | +3.06 | 68.1% | 120 |
| bad quarter | 2025 | 60 | 2,022 | +5.83 | 69.8% | 120 |
| bad quarter | 2025 | 250 | 1,533 | +8.70 | 72.5% | 120 |
| bad quarter | 2026 | 5 | 1,529 | +1.46 | 65.7% | 20 |
| bad quarter | 2026 | 20 | 1,501 | +0.95 | 63.0% | 20 |
| bad quarter | 2026 | 60 | 1,009 | -0.98 | 53.8% | 20 |

**Lead time** (median across all years of each signal's peak measured horizon, in sessions):

| signal | median peak h |
|---|---:|
| delivery spike up | 120 |
| delivery spike down | 120 |
| delivery trend up | 60 |
| delivery trend down | 120 |
| volume spike up | 60 |
| volume spike down | 120 |
| insider buy cluster | 60 |
| insider sell cluster | 120 |
| pledge increase | 120 |
| pledge release | 60 |
| bulk/block inst buy | 60 |
| bulk/block inst sell | 120 |
| promoter up | 60 |
| promoter down | 120 |
| bad quarter | 120 |
| peak quarter | 60 |
| FPI up | 60 |
| FPI down | 120 |
| MF up | 60 |
| MF down | 120 |
| insurance up | 60 |
| insurance down | 120 |

## 6. Look-back from every +/-30% excess move

A move is a 60-session excess return of at least +30% or at most -30% versus the Nifty 500
TRI, deduped to the first crossing per stock/direction/60 sessions: 65,292
moves. Recall is the share of matching-direction moves with that signal in the prior 90
sessions; precision is the share of that signal's firings followed by a matching-direction
move within 60 sessions; both are compared with the same stock's random sessions in the same
year.

| signal | n moves | recall | recall placebo | n firings | precision | precision placebo | lift | p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| delivery spike up | 37,248 | 1.54% | 1.61% | 3,399 | 30.5% | 28.5% | +1.90pp | 1.39e-02 |
| delivery spike down | 28,044 | 1.79% | 1.62% | 4,465 | 26.5% | 21.8% | +4.62pp | 7.46e-14 |
| delivery trend up | 37,248 | 2.66% | 2.70% | 17,014 | 30.3% | 31.4% | -1.07pp | 2.75e-03 |
| delivery trend down | 28,044 | 4.47% | 4.24% | 43,945 | 18.0% | 16.9% | +1.05pp | 4.53e-09 |
| volume spike up | 37,248 | 19.20% | 18.63% | 84,564 | 37.4% | 32.3% | +5.02pp | 5.60e-214 |
| volume spike down | 28,044 | 9.09% | 8.13% | 32,162 | 18.8% | 15.1% | +3.72pp | 1.13e-77 |
| insider buy cluster | 37,248 | 1.32% | 1.23% | 1,323 | 27.8% | 25.9% | +1.91pp | 1.13e-01 |
| insider sell cluster | 28,044 | 0.84% | 0.76% | 1,268 | 13.8% | 12.3% | +1.47pp | 1.11e-01 |
| pledge increase | 28,044 | 1.06% | 1.03% | 1,176 | 22.4% | 21.9% | +0.46pp | 7.03e-01 |
| pledge release | 37,248 | 0.67% | 0.65% | 851 | 26.7% | 26.3% | +0.36pp | 8.13e-01 |
| bulk/block inst buy | 37,248 | 1.06% | 1.02% | 1,374 | 26.1% | 27.7% | -1.53pp | 2.04e-01 |
| bulk/block inst sell | 28,044 | 0.53% | 0.49% | 855 | 15.3% | 14.8% | +0.55pp | 6.47e-01 |
| promoter up | 37,248 | 0.90% | 0.83% | 897 | 29.0% | 28.0% | +0.98pp | 5.15e-01 |
| promoter down | 28,044 | 1.75% | 1.72% | 1,866 | 21.5% | 20.2% | +1.30pp | 1.62e-01 |
| bad quarter | 28,044 | 6.04% | 6.07% | 9,200 | 16.5% | 16.9% | -0.38pp | 3.31e-01 |
| peak quarter | 28,044 | 2.44% | 2.31% | 6,454 | 8.3% | 8.2% | +0.12pp | 7.16e-01 |
| FPI up | 37,248 | 1.20% | 1.37% | 1,844 | 19.4% | 29.1% | -9.73pp | 3.73e-20 |
| FPI down | 28,044 | 1.25% | 1.41% | 2,681 | 10.3% | 11.2% | -0.93pp | 1.28e-01 |
| MF up | 37,248 | 1.08% | 1.11% | 2,055 | 16.2% | 20.7% | -4.49pp | 5.13e-07 |
| MF down | 28,044 | 0.46% | 0.53% | 1,372 | 7.4% | 8.4% | -0.99pp | 1.85e-01 |
| insurance up | 37,248 | 0.23% | 0.21% | 505 | 13.1% | 14.7% | -1.61pp | 3.06e-01 |
| insurance down | 28,044 | 0.14% | 0.14% | 509 | 4.9% | 6.4% | -1.50pp | 1.66e-01 |

Best precision lift: volume spike up, delivery spike down, volume spike down, insider buy cluster, delivery spike up. The lifts are economically small (about 1-5pp) and
recall is barely above the placebo base rate: the signals do not "call" the big moves, they
tilt the odds. `volume spike` has the highest precision lift (+5.0pp
at volume spike up), and
`FPI up`/`MF up` fire *less* often before up-moves than random dates (negative lift).

## 7. Same-direction pairs within 30 sessions

Two same-direction firings 1-30 sessions apart are one pair event, measured from the first
firing; each pair is compared with each member alone (all its firings) and with the members'
own placebo. The selected pairs' sample is small (23-2131 events); the top ten were ranked on the same 60-session mean they are shown with, so their q values are optimistic.

| pair | n | mean | median | hit | NW t | A alone | B alone | placebo | q(BH) | BH |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--:|
| delivery_trend_up + insurance_up | 36 | +18.23 | +21.49 | 75.0% | 2.86 | +2.54 | +0.04 | +4.00 | 2.00e-02 | yes |
| pledge_increase + promoter_down | 49 | +11.37 | +16.59 | 73.5% | 3.65 | +0.24 | +0.95 | +8.37 | 1.97e-03 | yes |
| delivery_trend_down + insurance_down | 153 | +10.49 | +12.61 | 79.1% | 2.83 | -0.92 | -1.91 | -0.28 | 2.19e-02 | yes |
| bulk_inst_sell + promoter_down | 26 | +9.79 | +6.21 | 69.2% | 8.66 | -2.21 | +0.95 | +5.04 | 3.25e-16 | yes |
| pledge_release + volume_spike_up | 311 | +9.49 | +2.89 | 57.6% | 3.42 | +2.29 | +1.34 | +6.36 | 4.15e-03 | yes |
| bulk_inst_sell + delivery_spike_down | 23 | +9.47 | +11.80 | 73.9% | 2.35 | -2.21 | +0.40 | +1.04 | 6.54e-02 | yes |
| delivery_trend_up + volume_spike_up | 2,131 | +9.11 | +5.04 | 58.0% | 3.66 | +2.54 | +1.34 | +3.78 | 1.95e-03 | yes |
| insider_buy_cluster + volume_spike_up | 494 | +8.92 | +3.76 | 61.7% | 4.09 | +3.87 | +1.34 | +5.48 | 3.94e-04 | yes |
| delivery_spike_down + peak_quarter | 155 | -12.71 | -4.54 | 41.3% | -1.86 | +0.40 | -3.81 | -3.35 | 1.71e-01 | no |
| bulk_inst_sell + delivery_trend_down | 44 | -31.18 | -15.35 | 27.3% | -2.74 | -2.21 | -0.92 | -10.63 | 2.78e-02 | yes |

Pairs do add in the two large combinations: `delivery_trend_up + volume_spike_up` (n = 2,131) +9.11% versus +2.54% / +1.34% alone; `delivery_trend_down + promoter_down` (n = 740) +8.81% versus -0.92% / +0.95% alone; `insider_buy_cluster + volume_spike_up` (n = 494) +8.92% versus +3.87% / +1.34% alone. The smaller top-ten pairs were
selected on the same 60-session mean they report and should be read as exploratory; the pair
event is measured from the first firing, so the second signal is confirmation inside 30
sessions, not the entry trigger.

## 8. Limits and honest caveats

- The signal set is deliberately simple: fixed thresholds, no fitted parameters, no
  cross-sectional ranking. That is what makes the placebo meaningful, and it is also why the
  effects are small.
- Market signals fire at most once per company/signal per 30 sessions. That removes the
  daily-state overlap (a delivery trend that lasts a quarter is one event) but it also means
  a genuinely persistent signal is measured once per episode, not weighted by how long it
  lasted.
- FPI/MF/insurance signals exist only from 2024-07 and promoter q/q only from 2022-01 (the
  shareholding filings before that carry their 2022 backfill `known_at`); their samples are
  eight quarters, not eight years. Filings known more than 120 days after their quarter end
  are dropped.
- `nse_insider` ends in 2026-05 and `index_tri` in 2026-10-16, so the last usable forward
  windows are shorter than 250 sessions; a cell's n falls with the horizon, and the 250-session
  cells cover events only up to about 2025-10.
- Placebo matching is by stock and calendar year, and the second null is by stock, year **and
  month**; neither matches volatility, momentum or market cap. A signal that fires in unusual
  states can still differ from random dates for that reason. The month-matched null is a
  stricter, ex-post conditioning: a real signal that fires in bad months can still be useful
  if it fires before the move.
- Benjamini-Hochberg uses the normal approximation to the Newey-West t, not an exact
  permutation p, and overlapping event windows are only partly corrected by the NW lags. The
  2019+ audit found stock-clustered t close to or above the NW t, so the NW t was not inflated
  by stock-level dependence.
- The top pair list was selected on the same 60-session mean it reports; its q values are
  optimistic and the pair result should be read as exploratory.
- 2010-2018 is NSE-only: the live BSE table carries no ISIN and its delivery column is corrupt
  (24-42% of rows exactly 100%), so BSE-only names are absent from the pre-2019 sample. 112 of
  the 1,665 2010-2011 NSE symbols have no 2012+ ISIN and their ~43k rows (1.3% of 2010-2018)
  are dropped. Size cells start in 2019 because `results_key` (the market-cap source) starts
  in 2017-06.
- The study is a description of held data, not a trading rule: no costs, no position sizing,
  no liquidity filter beyond the volume-signal floor.

## 9. Reproduce

```bash
# 2010-2018 extension of the truth price series (NSE only) + BSE 500 TRI proxy
python -m reality_engine.scripts.build_flow_snapshot --out .tmp/t235/snap_ext.duckdb   # ~6 min
# full study 2010-2026
python -m reality_engine.research.flow_signals --out .tmp/t235 --snapshot .tmp/t235/snap_ext.duckdb --start 2010-01-01  # ~13 min
python -m reality_engine.research.flow_events  --out .tmp/t235 --signals .tmp/t235/flow_signal.csv --snapshot .tmp/t235/snap_ext.duckdb --start 2010-01-01  # ~35 min
# 2019+ comparison (base snapshot)
python -m reality_engine.research.flow_signals --out .tmp/t235/s1fix --snapshot .../truth_2026-11-04.duckdb --start 2019-01-01  # ~6 min
```

Outputs: `flow_signal.csv` (the signal table), `signal_firings.csv`, `after_signal.csv`
(110 cells, now with `n_stocks` and `placebo_mean_month/diff_month/p_month/seeds_month`), `by_group.csv`
(size, sector, phase_200dma, phase_12m and the crossed phase_4 cells), `by_year.csv`,
`lookback.csv`, `moves.csv`, `pairs.csv` and `event_counts.csv`. The audit script and its
outputs are `.tmp/t235/audit_cells.py` and `.tmp/t235/audit/` (`audit_summary.csv`,
`audit_examples.csv`, `audit_meta.json`). Tests:
`python -m pytest reality_engine/tests/test_flow_signals.py -q` (16 passed).

## 10. Round 2: 2010-2026 after the audit fixes

The extended snapshot (`build_flow_snapshot.py`) adds 2010-01-04..2018-12-31: 3.28M NSE
price rows over 2,085 entities, the BSE 500 TRI proxy spliced to the Nifty 500 level on
2019-01-01, 2010-2018 bulk/block deals and 2015-2018 insider/pledge rows. The full run reads
10.61M price rows and writes 129,298 signals over 3,379 companies, 2010-01-05..2026-11-03
(89,801 of them are 2019+ after the fixes; 39,497 are 2010-2018). 127,411 signals have an
entry session. Benjamini-Hochberg at 10% is computed over all 4,622 return cells written and
1,251 pass; 26 of the 110 signal x horizon cells pass, and only 8 pass BH in the claimed
direction with both the same-year and same-month placebos at 10% or better. No signal level
that is not listed passes all three.

### 10.1 Survivors, 2010-2026

| signal | dir | h | n | stocks | mean % | median % | hit | NW t | year placebo % | month placebo % | p year | p month | q(BH) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| bad quarter | down | 5 | 9,150 | 1,694 | +1.162 | +1.828 | 64.2% | 13.53 | -0.003 | +0.241 | 0.048 | 0.048 | 3.4e-39 |
| delivery trend down | down | 20 | 8,781 | 2,412 | +0.732 | +2.343 | 59.2% | 3.30 | -1.340 | -0.184 | 0.048 | 0.048 | 7.0e-03 |
| promoter down | down | 20 | 1,670 | 854 | +1.156 | +2.476 | 59.6% | 2.23 | -0.402 | +0.726 | 0.048 | 0.048 | 9.5e-02 |
| delivery trend down | down | 5 | 8,863 | 2,448 | +0.231 | +0.898 | 57.2% | 2.80 | -0.347 | -0.354 | 0.048 | 0.048 | 2.7e-02 |
| promoter down | down | 5 | 1,698 | 864 | +0.405 | +0.931 | 58.3% | 2.35 | -0.198 | -0.119 | 0.048 | 0.048 | 7.6e-02 |
| FPI down | down | 5 | 2,457 | 1,173 | +0.405 | +0.718 | 57.8% | 3.28 | +0.125 | -0.025 | 0.048 | 0.048 | 7.4e-03 |
| delivery spike up | up | 5 | 3,903 | 1,199 | +0.415 | -0.451 | 45.3% | 3.37 | +0.117 | +0.214 | 0.048 | 0.095 | 5.7e-03 |
| promoter up | up | 5 | 817 | 515 | +0.624 | -0.418 | 47.2% | 2.64 | +0.228 | +0.342 | 0.048 | 0.095 | 4.0e-02 |

Reading: `bad quarter` is again the broadest and strongest effect (mean almost 3x the next
cell, hit 64%, q at the numerical floor, positive in all four market phases). `delivery trend
down` (distribution) now survives at 5 and 20 sessions over 17 years, but the 20-session mean
is 0.73% and it clears the placebo only against the stock's own falling base rate.
`promoter down` and `FPI down` are 0.4% five-session effects in the claimed direction; the
promoter sign is the dilution story the audit found, and the 20-session promoter mean is 1.16%.
`delivery spike up` is marginal: the month-matched p is 0.095 (the 10% edge), the median is
-0.45% and only 45.3% of events beat the benchmark, so the mean is a right tail. `promoter up`
is the same shape (median -0.42%, hit 47.2%).

`volume spike up` is a **fade**, not a survivor in the claimed direction: -0.157% at 5
sessions (BH pass, two-sided) and its mean is below the same-year and same-month placebo at
every horizon. `insider buy` +0.59% at 5s passes BH but the month-matched placebo is +0.585%
(p = 0.48): over the longer sample it is stock selection, not an insider effect. No pledge,
bulk/block, MF, insurance or peak-quarter cell passes both placebos in the claimed direction.

### 10.2 What the fixes changed on 2019+ (before -> after)

| cell | n before | mean before | n after | mean after | change |
|---|---:|---:|---:|---:|---|
| delivery spike down, 5s | 4,408 | +1.05% | 1,993 | +0.16% | cooldown removes 58% repeat firings; NW t 6.88 -> 0.88 |
| delivery spike up, 5s | 3,326 | +1.08% | 1,717 | +0.58% | NW t 6.12 -> 2.93; months p 0.19 in the audit |
| delivery trend down, 5s | 43,535 | +0.15% | 4,603 | +0.21% | state-days collapse to 4,603 episodes |
| delivery trend up, 20s | 16,539 | +0.45% | 2,321 | +1.22% | the overlapping state was hiding a stronger 20-session mean |
| volume spike up, 250s | 70,286 | +11.32% | 22,390 | +10.45% | still far below its placebo |
| promoter down, 20s | 1,785 | +1.16% | 1,662 | +1.20% | 6.8% stale filings removed; effect unchanged |
| bad quarter, 5s | 9,150 | +1.16% | 9,150 | +1.16% | no rule touched it |
| all signals | 222,964 | | 89,801 | | market 187,555 -> 54,862; promoter 2,974 -> 2,729; categories 9,593 -> 9,292 |

### 10.3 Per year, 5-session mean (n), 2010-2026

| year | bad quarter | delivery trend down | delivery spike up | volume spike up | promoter down |
|---:|---:|---:|---:|---:|---:|
| 2010 | - | +0.95 (637) | +0.85 (231) | -1.24 (789) | - |
| 2011 | - | +0.71 (457) | -0.11 (311) | -0.43 (853) | - |
| 2012 | - | -0.17 (510) | +0.00 (234) | -0.24 (1,101) | - |
| 2013 | - | +0.05 (416) | -0.63 (245) | -0.35 (902) | - |
| 2014 | - | +0.10 (452) | +0.61 (189) | -0.16 (1,769) | - |
| 2015 | - | -0.99 (376) | +0.71 (241) | +0.10 (1,581) | - |
| 2016 | - | +0.18 (433) | +0.96 (207) | -0.14 (1,882) | - |
| 2017 | - | +0.71 (486) | +0.83 (210) | -0.01 (2,659) | - |
| 2018 | - | +0.45 (451) | -0.19 (272) | -1.22 (1,985) | - |
| 2019 | - | +0.37 (402) | +0.60 (258) | -0.56 (1,525) | - |
| 2020 | -1.26 (407) | +0.25 (552) | +1.68 (277) | -0.02 (2,662) | - |
| 2021 | +1.24 (1,119) | -0.38 (580) | +0.71 (244) | +0.22 (3,524) | - |
| 2022 | +1.28 (1,190) | +0.01 (523) | +0.33 (266) | -0.37 (3,055) | +1.36 (253) |
| 2023 | +0.24 (1,306) | +0.09 (596) | +0.18 (232) | +0.37 (4,398) | -0.23 (342) |
| 2024 | +1.32 (1,568) | +0.53 (634) | +0.22 (183) | -0.07 (5,017) | +0.21 (448) |
| 2025 | +1.79 (2,031) | +0.71 (708) | +0.03 (164) | -0.59 (4,133) | +1.12 (381) |
| 2026 | +1.46 (1,529) | -0.13 (650) | +0.24 (139) | +0.14 (3,926) | -0.35 (274) |

Call-outs:
- **2011** (euro crisis / inflation): only distribution (`delivery trend down`) is positive
  and reliable (+0.71%, 457 events); `delivery trend up` is -0.97% and `volume spike up` -0.43%.
- **2015-16**: distribution flips negative in 2015 (-0.99%, 376) and recovers in 2016; the
  accumulation side is positive both years (+1.14%, +0.27%).
- **2018-2020 consolidation**: 2018 hurts every delivery signal except distribution; 2019 is
  the worst year for `delivery trend up` (-1.52%, 221); in the **2020 crash** `bad quarter`
  flips sign (-1.26%, 407 - bad-results stocks bounced) while `delivery spike up` (+1.68%) and
  `delivery trend up` (+1.73%) are their strongest years.
- **2021-24 rally**: `bad quarter` is positive every year (+1.24, +1.28, +0.24, +1.32);
  distribution is positive in 2021, 2023 and 2024 (+0.37, +0.09, +0.53); the accumulation
  spike is positive throughout (+0.71, +0.33, +0.18, +0.22).
- **2025-26**: `bad quarter` strengthens to +1.79% / +1.46%; promoter down is +1.12% in 2025
  and -0.35% in 2026; delivery spike down is +0.34% / +1.53%.

### 10.4 Crossed phase: index vs its 200-session mean x 12-month return sign (5s)

| signal | above + 12m up | above + 12m down | below + 12m up | below + 12m down |
|---|---:|---:|---:|---:|
| bad quarter | +0.996 (7,253) | +1.880 (486) | +1.867 (1,225) | +1.147 (186) |
| delivery trend down | +0.205 (5,366) | +0.414 (662) | +0.177 (1,196) | +0.285 (1,639) |
| delivery spike up | +0.453 (2,229) | +0.207 (248) | +0.173 (601) | +0.551 (825) |
| promoter down | +0.303 (1,120) | +0.948 (169) | +0.756 (318) | - |
| FPI down | +0.669 (1,128) | +0.200 (220) | +0.350 (1,014) | - |
| volume spike up | -0.094 (30,586) | -0.487 (2,528) | -0.423 (4,398) | -0.141 (4,249) |

(`mean % (n)`; cells with n < 100 omitted. `bad quarter` is positive in every phase;
`delivery spike up` is positive in three of four and its largest cell is the above-200dma,
12m-up rally phase. `volume spike up` is negative in all four - a fade in every regime.)

### 10.5 Fading/strengthening and lead time

Median measured horizon at which the signed excess peaks, early (2010-2015 years) vs late
(2020-2026 years), sessions:

| signal | early | late |
|---|---:|---:|
| delivery spike up | 60 | 120 |
| delivery trend up | 40 | 60 |
| delivery spike down | 120 | 120 |
| delivery trend down | 120 | 120 |
| volume spike up | 60 | 60 |
| volume spike down | 120 | 120 |
| insider sell | 120 | 120 |
| bulk/block buy | 60 | 60 |
| bulk/block sell | 120 | 120 |

No shortening: the two delivery signals that changed moved *later* (spike up 60 -> 120,
trend up 40 -> 60), and the rest are unchanged. The 5-session cells are a front edge, not
the peak; the systematic effect peaks at 60-120 sessions and is mostly gone by 250.

### 10.6 Look-back and pairs, 2010-2026

Recall (share of matching-direction +/-30% moves with a firing in the prior 90 sessions) is
still barely above the same-stock random-date base rate: 3.31% vs 2.91% for delivery spike
down, 20.4% vs 19.9% for volume spike up, 6.35% vs 5.92% for delivery trend down. Precision
lifts (share of firings followed by a matching move within 60 sessions, minus the placebo):

| signal | firings | precision | precision placebo | lift | p |
|---|---:|---:|---:|---:|---:|
| delivery spike down | 4,917 | 21.1% | 17.2% | +3.85pp | 8.7e-13 |
| volume spike up | 41,864 | 29.1% | 26.1% | +2.96pp | 2.6e-43 |
| delivery trend down | 8,951 | 20.6% | 18.2% | +2.39pp | 4.8e-09 |
| volume spike down | 25,371 | 13.8% | 11.9% | +1.83pp | 2.0e-19 |
| insider sell cluster | 2,006 | 14.7% | 13.1% | +1.61pp | 3.3e-02 |

The signals do not call big moves; they tilt the odds by 1.6-3.9pp, and the two volume
signals carry the highest precision lifts while the delivery signals carry the cleanest
event-study means.

Same-direction pairs (first firing, 60-session mean): `delivery trend down + promoter down`
n=64, +9.34%, NW 9.8, placebo +0.97%; `insider buy + volume spike up` n=595, +9.21%, NW 4.4,
but the pair's own placebo is +4.51%, so the add over the members is real but far smaller
than the raw mean; `bulk/block sell + pledge increase` n=32, +8.78%, NW 9.7. The earlier
stage-1 top pairs (small samples selected on the same metric) do not all reappear; the pair
table remains exploratory and 361 cells are in the BH denominator.

### 10.7 Reading

1. One effect is broad and regime-independent: **a bad quarter at 5 sessions** (+1.16%,
   hit 64%, present in all four crossed phases). It is an announcement-window continuation,
   not a pre-announcement signal.
2. The **distribution** side of delivery (`delivery trend down`) is the only delivery signal
   that survives at both 5 and 20 sessions across 17 years; it is small (+0.23%, +0.73%) and
   its 20-session cell is weaker than its stage-1 2019+ figure.
3. The **accumulation** side (`delivery spike up`) is a right-tail bounce: median negative,
   hit below 50%, month-matched p at the 10% edge. It should not be traded as a majority
   effect.
4. **Volume spikes are a fade** in every phase and every horizon (negative signed means,
   placebo p = 1.0); `volume spike up` is the only large cell that passes BH in the negative
   direction.
5. **Ownership changes** (promoter/FII down) are 0.4% five-session effects in the claimed
   direction; the promoter effect is dilution-shaped, not informed selling. Insider buys do
   not survive the month-matched null over the long sample.
6. The 2010-2018 extension adds the 2011 and 2015-16 stress periods and the 2020 crash; the
   effect that holds through them is the bad-quarter reversal, not the delivery signals.
