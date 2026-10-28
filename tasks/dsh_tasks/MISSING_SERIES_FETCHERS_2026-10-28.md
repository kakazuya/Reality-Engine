# Task — fetcher scripts for the data the architecture says is still missing: F&O bhavcopy, equity bhavcopy gaps, commodity series

## Goal
`tasks/arch_v3/COVERAGE.md` and `tasks/answer_bench/REPORT_v0.md` name the missing data:
- commodity series, 62 cases (mkt_commodity_daily holds 13 series, with no known_at);
- equity bhavcopy, 19;
- F&O history (contracts, OI, rollover, basis), 9+ cases, plus 5 Reddit `fno_vs_cash_flow` cases.

## Do
1. **`reality_engine/scripts/fetch_fo_bhavcopy.py`:**
   - NSE F&O daily bhavcopy (UDiFF/legacy zip in nsearchives), 2019-01-01 to today;
   - arguments: `--from/--to/--out` (default `D:\RealityEngine\raw\fo_bhavcopy`), `--interval` (default 0.4 s; probes showed NSE took 400/min bursts unblocked), resume, back-off on 403/429/503, cookie warm-up via `reality_engine.ingestion.nse_client.NSEClient`;
   - a parser to tidy rows: date, symbol, instrument, expiry, strike, option type, OHLC, settle, OI, change in OI, contracts, value.
2. **Equity bhavcopy gaps:** find which trading dates lack equity bhavcopy in the held price tables (bounded connect_ro queries). Write `fetch_eq_bhavcopy_gaps.py` to fill exactly those dates.
3. **Commodity series:** list which commodities the bank's cases need (master bank GAP_ROLLUP G12 / commodity_series cases) vs the 13 held. Write `fetch_commodity_series.py` for free official sources with no login and no API key: for example MCX bhavcopy, the RBI reference rates, the World Bank pink sheet and public EIA/FRED CSVs. Record known_at as the publication time.
4. **Tests:** offline, with fixture files for every parser, in `reality_engine/tests/test_missing_series_fetchers.py`.
5. **Dry-run plan:** the request counts and a time estimate per fetcher. No live calls; the controller runs the fetches.

## Rules
- **No network** (the controller runs the fetches). Read-only DBs. Write only in this worktree. No commits.
- No logins, no captcha bypass, no paid APIs.

## Acceptance checks
`python -m unittest reality_engine.tests.test_missing_series_fetchers` passes. The report gives the exact commands and time estimates.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_missing_series_fetchers
```

## Report
Give:
- the sources and URL patterns;
- the commodities covered vs the ones needed;
- the commands;
- the estimates;
- your tool-call count.
