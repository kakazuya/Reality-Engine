# T-235 stage 1 brief: capital-flow early-warning signals + event study (scripts only)

Ticket: T-235 (Shivam 22 Nov 2026). Reviewer: Wolf (Opus).

Goal: Shivam: "prices are a function of capital; are there early signs of money moving out of (or into) a stock -
a delivery spike, a promoter holding change, a bad quarter, or for a cyclical a record quarter - and what happened
after, how fast, and has it faded or got stronger over the years?" Build dated per-stock signals from held market
data and measure what followed each. Stage 1 = signals + after-signal study on held data (2019+). A 2010-2018
backfill (T-236) is being fetched; write everything so a rerun over 2010+ needs only a new date range.

Evidence (all read-only):
- Truth snapshot `reality_engine/data/snapshots/truth_2026-11-04.duckdb` (`px_daily` adjusted + total-return; company =
  ISIN issuer code); panel builder `reality_engine/research/factor_weights.py` (`build_panel`), month-end reward engine
  `reality_engine/research/factor_rewards.py`, method doc `docs/research/T-207_factor_rewards.md` (peak trap: record
  earnings lose at 24m; promoter change and delivery are stable rewarded factors).
- `equity_intelligence.db` (path in `tasks/DATA_INVENTORY.md`): `daily_price_delivery` (8.8M), `mkt_bse_delivery_daily`,
  `bulk_block_deals` (272k, named parties), `insider_trades_v2` (333k), `mkt_nse_insider`, `mkt_bse_insider`,
  `shp_facts` / `shp_index` (quarterly holding by category incl. pledge), `mkt_fii_dii_cash`, `mkt_nsdl_fpi_daily`,
  quarterly results tables (find the dated PAT/revenue source the T-118 panel uses).
- Timing rule: `project_filing_timing_rule` / FRAMEWORK: a filing before 15:30 IST counts on day T, after on T+1;
  shareholding is known on its filing date, not the quarter end.

Steps:
1. `reality_engine/research/flow_signals.py`: one table `flow_signal(company, date_known, signal, direction, strength,
   detail)`; signals (thresholds fixed in code before any outcome is seen, written in the doc):
   delivery spike vs own 60-session median (with the day's price sign: up = accumulation, down = distribution);
   delivery-share trend; volume spike on a 200-session-mean break; promoter/insider net sell or buy clusters (count and
   value over 30 days); new pledge / pledge increase; bulk/block net by institutions (named party classified
   FII/MF/insurance/other by name patterns, list the rules); FPI / MF / insurance / promoter stake change q/q at filing
   date; bad quarter (PAT and margin vs the company's own history); peak quarter (margin/PAT at own 5-year high).
2. `reality_engine/research/flow_events.py` after-signal study: excess return vs market and vs the same stock's
   random dates (placebo, 20 seeds) at 5 / 20 / 60 / 120 / 250 sessions; by size tercile, sector, year, and market
   phase (index vs 200-session mean, 12m return sign); hit rate, mean, median, Newey-West t, BH 10% across all cells.
   Per year so fading/strengthening and shortening lags are visible (median days to the peak excess move).
3. Look-back study: every move of -30% / +30% excess within 60 sessions; which signals fired in the 90 sessions before;
   per signal precision (moves after firing / firings) and recall (moves preceded / moves), vs placebo.
4. Pairs/combos: top 10 signal pairs firing within 30 days of each other vs each alone (same placebo and BH).
5. Tests (synthetic) for timing (no signal before its date_known), thresholds, placebo; doc
   `docs/research/T-235_capital_flow.md` with tables and plain-English findings; DEVELOPER_GUIDE line.

Files: the two new modules, `reality_engine/tests/test_flow_signals.py`, the doc, DEVELOPER_GUIDE. No other file;
do not edit tasks/STATE.md. Outputs to `.tmp/t235/` (D: may be denied to the sandbox).

Pitfalls: a signal must use only data known at date_known (holdings on filing date; results on the 15:30 rule);
adjusted prices for returns, raw for delivery value; survivorship: keep delisted companies; overlapping windows
inflate t - use Newey-West with horizon-1 lags; memory: stream per year, keep peak RAM < 3 GB (16 GB machine, other
jobs running).

Accept: tests pass; typecheck clean; doc tables for every signal x horizon with counts behind every percentage;
report under 25 lines: signals that survive placebo + BH at each horizon, which faded/strengthened by year, lead
times, look-back precision/recall of the best five.

Stop if: a signal needs data not held (report it); RAM > 6 GB.

Budget: about 4 hours, DeepSeek max effort.
