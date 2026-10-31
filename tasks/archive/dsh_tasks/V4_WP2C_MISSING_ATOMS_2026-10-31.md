# Task — v4 WP2c: fill the missing atoms and fix quarterly vs year-to-date

## Goal
The fact store has rows for 31 of 43 held atoms. Fill what the held data can fill, and fix the XBRL period mix that makes own estimates unreliable. First read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`.

## Work
1. **Period fix.** 369 of 1,233 own-estimate pairs (29.9%) compare an annual or year-to-date number with a quarterly one, because the pilot store mixes them. Find the OneD/FourD XBRL context handling (decision log 2026-10-19; `results_xbrl.db`) and store true single-quarter values, with a `period_kind` and how each was derived (reported or YTD difference). Rebuild `own_estimate` and the bands; report band widths before and after. Never derive a quarter when a needed YTD value is missing or restated: leave it empty and count it.
2. **Missing atoms.** From `reality_engine/query/v4/build_membership.py` `NOT_BUILT`: `price.rsi`, `price.sma` (live `daily_price_delivery` has them, or compute from pilot closes with no look-ahead), `fin.capex` (cash flow lines in held filings; `capex_project` is announcements and is a different atom), `macro.policy` (`policy_events`), `macro.claim` (`macro_all.db`; check `.tmp/pilot_all/macro_all.db`, a rebuild that was never installed), `macro.index_close`, `macro.flow`, `macro.etf_premium`, `hold.fpi_limit_utilised`. Also the empty ones: `hold.pledge_pct`, `flows.net_inr`; and `hold.pct` for DII and MF, `fin.receivables`, `fin.capacity_utilisation`.
   - For each: filled with row count, or a fetch ticket naming the exact source, or truly absent. Do not fetch in this task.
3. **Prices for the 11 pilot names with blank symbols.** They have no open, high, low, volume or delivery. Resolve their BSE codes or new symbols, and fill from held data.
4. **F&O size.** About 2 GB of the 2.3 GB store is `macro.oi` per contract. Keep behaviour, but serve it from a separate attached file so the core store stays small.

## Outputs
Update `fact_view.sql` and the builders; a new `.tmp/fact_v4_pilot.db` and `.tmp/v4.db` for the controller to install, with the rebuild commands. Do not touch `decompose.py`, `execute.py` or `grade_v2.py`: an integration worker is running on them.

## Acceptance checks
- Atom table: 43 rows, each with status, row count and ISIN coverage.
- 30 hand-checked single-quarter values against the filing's own quarter column.
- Replay check still shows 0 PIT violations; `known_at` from the filing record.
- Tests pass.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_fact_view.py reality_engine/tests/test_v4_vocab_claim.py -q
```
