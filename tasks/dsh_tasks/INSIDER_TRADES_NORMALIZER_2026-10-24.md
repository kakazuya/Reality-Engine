# Task: build the normalized `insider_trades` table from the data we already have

Owner: Shivam (asked 2026-10-24: "fill the empty insider-trades table"). Reviewer: Claude. Worker: you (DeepSeek), in a git worktree.

## Situation (verified 2026-10-24 by Claude, read-only queries on `reality_engine/data/equity_intelligence.db`)

- `insider_trades` (legacy; columns id, symbol, isin, acquirer_name, category_of_person, transaction_type, num_shares,
  value_inr_lacs, mode_of_acquisition, acquisition_date, intimation_date) has **0 rows**. Its only filler is
  `NSEClient.fetch_insider_trades()` (`reality_engine/ingestion/nse_client.py:323`), whose NSE endpoint now returns
  nothing. Its only reader is `repository.get_recent_insider_trades()` (`reality_engine/db/repository.py:1515`).
- Real insider data is already loaded by `reality_engine/scripts/load_market_raw.py`:
  - `mkt_nse_insider`: 176,089 normalized NSE trades, 2,198 symbols, `disseminated_at` 2019-01-01 .. 2026-05-02
    (columns: did, pid, symbol, company, acquirer_name, person_category, security_type, transaction_type,
    acquisition_mode, securities_qty, securities_value, buy_qty, buy_value, sell_qty, sell_value, before_shares,
    before_pct, after_shares, after_pct, acq_from, acq_to, intimation_date, disseminated_at, exchange, xbrl, raw_json).
  - From 2026-05-03 NSE moved to new PIT XBRL filings: `mkt_nse_pit_filings` (3,792 filings, app_id, symbol,
    regulation, submission_type, broadcast_at, disseminated_at, revision_remark, prev_app_id, xml_url) and
    `mkt_nse_pit_xbrl_facts` (158,608 facts: xml_file, context_id, concept, seq, value, unit), parsed by
    `parse_pit_xml` in load_market_raw.py. **No code turns these facts into trade rows yet.**
  - `mkt_bse_insider`: 153,904 BSE rows (file, line_no, company, isin, person, raw_json with BSE's column labels,
    e.g. "Shares acquired / disposed(No. of shares)", "...(Value of Security)", "...(Transaction type ...)").

## What to build

1. `reality_engine/scripts/build_insider_trades.py` (idempotent, `--dry-run`, `--db PATH`), which rebuilds a
   normalized table **`insider_trades_v2`** (do not drop or alter the legacy table; leave it empty):
   one row per disclosed transaction with: source (`nse_legacy` | `nse_pit_xbrl` | `bse`), source_key (stable unique
   id per source row), symbol, isin (resolve via `master_companies` / `symbol_isin_history`, ISIN-history aware),
   company, person_name, person_category, transaction_type (normalized to BUY/SELL/PLEDGE/REVOKE/OTHER),
   mode (market purchase/sale, off-market, ESOP, etc. normalized), security_type, qty, value_inr,
   before_pct, after_pct, trade_from, trade_to (ISO dates), intimation_date, **known_at** (exchange dissemination
   timestamp, IST; this is the point-in-time key for backtests), revision flag / supersedes key where known.
2. NSE PIT XBRL → trades: group facts by xml_file + context; map the concepts (inspect the distinct `concept` values
   first and document the mapping in the script header). Join filings for symbol/known_at. Handle revisions
   (`submission_type`, `prev_app_id`) so a revised filing supersedes the original.
3. Dedupe across NSE and BSE: the same trade is often filed on both. Define and document the matching key
   (ISIN + person (normalized) + qty + trade dates); keep one row and record the other source in a `also_on` column.
   Report how many matched.
4. Point `repository.get_recent_insider_trades()` at `insider_trades_v2` with the same output column names the
   legacy callers expect (alias columns), filtering on `known_at <= as_of` when `as_of_date` is given (no look-ahead).
5. Tests in `reality_engine/tests/test_insider_trades.py` (unittest, in-memory SQLite fixtures, no network, no live DB):
   mapping of each source, XBRL grouping, revision supersede, NSE/BSE dedupe, PIT filter.
6. A coverage report printed at the end: rows per source per year, distinct ISINs, null rates of qty/value/known_at,
   and the May-2026 seam (show rows per month 2026-03..2026-10 so the NSE legacy → XBRL hand-over has no hole).

## Rules

- Read the live DB **read-only** (`file:...?mode=ro`). Do not write to any live database; Claude runs the build after
  review. Use a temp copy or in-memory fixtures for your own checks.
- No network calls, no paid APIs. Match the surrounding code style (comment density, naming).
- Run `python -m unittest reality_engine.tests.test_insider_trades` and the existing quick suite before finishing.
- Final answer: what you built, the concept mapping, the dry-run coverage report numbers (from a `--dry-run` against
  the read-only live DB), test results, and anything you could not map.
