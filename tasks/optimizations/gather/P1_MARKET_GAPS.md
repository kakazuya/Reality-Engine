# Task P1 — close the market-data gaps since 2019 (full access, data job)

## Goal
Shivam's priority 1: price/volume/delivery with correct labels (BSE+NSE), FII/DII cash, insider, bulk and block
deals for every scrip since 2019-01-01, verified by a coverage check — not by logs.

## Known gaps (manager check, 2026-10-26)
- **Bulk and block deals:** `equity_intelligence.db:bulk_block_deals` holds one day (2026-09-18). Raw files on
  `D:\RealityEngine\raw\raw_market\{nse_bulk,nse_block,bse_bulk,bse_block}` cover 2026-10-14..10-24 only.
- **NSE full bhavcopy** (`mkt_nse_full_daily`) starts 2019-06-27: Jan–Jun 2019 missing. Check whether
  `mkt_nse_eq_daily` + `mkt_bse_delivery_daily` already cover those sessions; fill NSE delivery for them if an archive
  exists.
- **NSE insider** (`mkt_nse_insider`): `intimation_date` has '-' and dates up to 2036. Parse/clean the dates; keep
  the raw value in a separate column.
- Confirm BSE eq/delivery, FII/DII cash and NSDL FPI daily have every trading session 2019-01-01..2026-10-23 (list
  any missing sessions against the NSE trading calendar).

## How
- Reuse `reality_engine/scripts/fetch_nse_api_raw.py` (datasets nse_bulk, nse_block) and `fetch_bse_api_raw.py`
  (bse_bulk, bse_block), backfilling 2019-01-01 → today in date windows the APIs accept; then
  `load_market_raw.py --sources nse_bulk,nse_block,bse_bulk,bse_block`. Raw files go under
  `D:\RealityEngine\raw\raw_market\` only.
- Polite rate: ≥1 s between requests per host, retries with backoff, resumable via the existing `_manifest.csv`.
- Labels: every deal row carries date, exchange, ISIN (resolved via `master_companies`/ISIN history), symbol,
  client name, buy/sell, quantity, price, deal type (bulk/block). Report unresolved ISINs.

## Write scope (the real fence — full access removes the OS sandbox)
- Network: only nseindia.com, nsearchives.nseindia.com, bseindia.com, api.bseindia.com.
- Live DB writes: only the bulk/block tables, `mkt_nse_insider` date columns, and any missing session rows in the
  market tables above, in `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\equity_intelligence.db`.
  Short transactions (commit per window); another worker may read the DB.
- Never touch `document_chunks`, vector indexes, other DBs, `.git/config`, `plugins/dsh-worker/`, `~/.dsh`.
- Code changes in this worktree only; do not commit (the manager does).

## Acceptance checks
1. Coverage table per dataset: sessions held / trading sessions 2019-01-01..2026-10-23, rows, distinct ISINs, missing
   sessions listed (or "none").
2. Bulk/block: rows per year per exchange; 5 spot rows cross-checked against the raw file.
3. NSE insider: count of bad dates before/after; 5 cleaned examples.
4. Tests for any changed parser (`python -m unittest` on the touched test modules).

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_*market*.py"
```

## Report
Coverage table, what was fetched (files, MB, time), what could not be fetched and why, tool calls.
One line per phase to `.tmp/PROGRESS_NOTES.md`.
