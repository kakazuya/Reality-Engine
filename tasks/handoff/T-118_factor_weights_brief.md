# T-118: which held facts actually move prices 6 months, 1 year and 2 years ahead (factor weight study, prototype)

Ticket: T-118

Goal: a point-in-time study over the whole listed universe, 2019-2026, that ranks candidate factors by how well they
explain forward 6-month, 12-month and 24-month total returns. Shivam's objective (8 Nov, `tasks/RULINGS.md`): predict
6m-2y prices from the least reliable data; focus on heavyweight factors. This study tells us which extractions matter.
It is research code; no trading rules, no model calls.

Files (only these): new `reality_engine/research/factor_weights.py` (create the folder with `__init__.py` if absent),
new `reality_engine/tests/test_factor_weights.py`, new `docs/research/T-118_factor_weights.md` (method + results),
one line in `docs/DEVELOPER_GUIDE.md` pointing at it. Outputs only under `.tmp/t118/`.

Evidence (Opus, 8 Nov; read-only):
- DuckDB snapshot `reality_engine/data/snapshots/truth_2026-11-04.duckdb` (open `read_only=True`; in a worktree use
  the main checkout path `C:/Users/warri/Downloads/Info_Diffusion_Model/reality_engine/data/snapshots/...`). Tables:
  - `px_daily` (exch, entity_id, date, isin, symbol, close, volume, value_inr, delivery_pct, adj_close, tr_close ...):
    7.3 M rows; `tr_close` is the total-return series (dividends and splits adjusted). Prefer NSE rows, BSE when a
    company has no NSE row on that date.
  - `results_key`: one row per XBRL results filing (trading_isin, symbol, consolidated 'Consolidated'/'Non-Consolidated',
    period_start, period_end, fy_start, `known_at_utc` = when the market saw it, RevenueFromOperations,
    ProfitLossForPeriod, ProfitOrLossAttributableToOwnersOfParent, FinanceCosts, Depreciation..., Basic EPS, PaidUpValue,
    FaceValue, InterestEarned/Expended and NPA fields for banks, ytd_* columns). ~107k filings, 2018-2026.
  - `shp_index` (isin, quarter_end, promoter_pct, public_pct, `known_at_utc`), `company_industry` (isin, macro, sector,
    industry), `index_tri` (index_name, date, tri) for the Nifty 500 / Nifty 50 benchmark,
    `bse_insider` / `nse_insider` (insider trades), `symbol_isin_history` (ISIN changes), `security_master`.
- Point in time: a fact is usable only from the first trading session after `known_at_utc` (IST: a filing after 15:30
  counts from the next session; see memory rule in `docs/DB_BUILD_GUIDELINES.md` / `tasks/RULINGS.md`).

Method (follow it; deviations need a reason in the doc):
1. Rebalance dates: last trading day of each month, 2019-06 to the last date with a full forward window per horizon.
2. Universe per date: companies with an adjusted price that day, median daily traded value over the prior 60 sessions
   >= Rs 1 crore, at least 250 sessions of price history. Keep delisted companies while they traded (no survivorship).
3. Per company per date, from facts known by that date (consolidated where the company files it, else standalone,
   never mixing within one series):
   - growth: TTM revenue YoY, TTM PAT YoY, latest-quarter PAT YoY, PAT growth acceleration (this quarter's YoY minus
     last quarter's YoY);
   - quality: TTM operating margin and its YoY change, TTM ROE proxy (TTM PAT / book value if available, else skip),
     finance cost / revenue;
   - valuation: TTM earnings yield (TTM EPS / price), sales yield, (book yield if book value is derivable);
   - ownership: promoter % change over 1 and 4 quarters; insider net buy value over the prior 3 months / market cap;
   - price: 12-1 month momentum, 1-month reversal, 12-month volatility, size (log market cap from paid-up capital /
     face value x price), delivery % 3-month mean.
   Winsorise each factor at 1%/99% per date; z-score within date; also a sector-neutral version (z within sector).
4. Targets: forward total return over 126, 252 and 504 sessions from tr_close, minus the benchmark TRI over the same
   window (excess return).
5. Statistics per factor x horizon: monthly Spearman rank IC (mean, t-stat with Newey-West lags = horizon in months - 1),
   hit rate (share of months IC > 0), top-minus-bottom quintile excess return, coverage (companies per month), and the
   same split by period (2019-2021 vs 2022-2026) and by size tercile. Then a joint view: cross-sectional regression of
   excess return on all z-scored factors per month (Fama-MacBeth), mean coefficients and t-stats.
6. Output: `.tmp/t118/factor_ic.csv`, `.tmp/t118/fama_macbeth.csv`, and `.tmp/t118/T-118_factor_weights.html` (one
   table per horizon, factors ranked by |t-stat|, with coverage); copy the HTML to
   `D:/RealityEngine/reports/2026-11-08_t118_factor_weights.html` ONLY if your sandbox can write there, else say so.

Steps:
1. Tests first (`test_factor_weights.py`, tiny in-memory DuckDB fixtures): point-in-time (a filing known after the
   rebalance date is not used; after 15:30 IST counts next session), TTM built from four quarters (and from ytd fields
   when a quarter row is missing), no consolidated/standalone mixing, forward return from tr_close, IC sign on a
   planted factor.
2. Build the panel; print its size per year and factor coverage before computing statistics; stop and report if
   coverage of the growth factors is under 40% of the universe in any year after 2019.
3. Compute and write outputs. Keep memory under 6 GB (process year by year; DuckDB queries, not pandas joins of the
   full price table).
4. Doc `docs/research/T-118_factor_weights.md`: method, the PIT rule, the results tables (top 10 per horizon), caveats
   (look-ahead risks checked, small-cap noise, 2020 crash months). Final answer starts with `Docs updated:` and gives the
   ranked factors per horizon with t-stats.

Accept: test file passes; outputs exist; the doc states coverage per year and the ranked factors per horizon.
Limits and pitfalls:
- Read-only on every database; outputs under `.tmp/t118/` only. No model calls, no new dependencies (duckdb, pandas,
  numpy, scipy are installed; check before importing anything else).
- Point-in-time is the whole value of this study: never use `period_end` as the availability date.
- A 504-session forward window ends after the data for recent dates: drop those dates for that horizon, never pad.
- Bank and insurer P&L lines differ (InterestEarned etc.): compute their growth factors from PAT and InterestEarned;
  margin factors only for non-financials (company_industry.macro or sector says Financial Services).
- Run the test file alone, one process.
Budget: 160 tool calls, 3 hours.
Stop if: results_key has no consolidated/standalone flag usable for a series, or the price table has no total-return
series for most companies: report what you found and stop.
