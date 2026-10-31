# Progress notes — v4 lookup repair (31 Oct 2026)

- Blank `as_of` defaults to `DEFAULT_AS_OF = 2026-10-23` in `reality_engine/query/v4/run.py` (one line for Shivam to change) and the answer prints it as an assumption.
- Executor: a named dim the atom's rows do not carry is ignored; `exchange=BSE` on the NSE-first close stays a typed NID; `lag=ytd` widens to Jan-1..date and lifts high/low to max/min_with_date; a named non-session date snaps to the last session and says so.
- `f.cagr` asks get their N-year window in the decomposer; the formula already reads price closes.
- Holdings: new `fact_view_holdings_isin.sql` + `build_membership` step (and `--holdings-only` install path) joins `shp_index` by symbol through `symbol_isin_history`; patched `.tmp/fact_v4_pilot.db` gives hold.pct 39 -> 57 of 60 entities (WPIL + two unnamed ISINs stay NID), 1,596 -> 2,386 rows.
- Gate (same runner, same installed store): strict 273 -> 360 (+87), 0 lost; 0 PIT breaches. Contract count is not truth.
- 20 hand-graded: 7 fully right / 10 partial (a value right, another ask leg missing) / 3 wrong measure; the blank-as_of class is smaller than the review's estimate. Items 4-7 were already built before the cheap test finished — flagged in the report.
- Tests: 57 passed on the required three files; 69 passed including `test_v4_fact_view.py`.
