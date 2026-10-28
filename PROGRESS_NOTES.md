# Progress — missing-series fetchers (F&O bhavcopy, equity gaps, commodities)

## 2026-10-28 — done

- Read `tasks/arch_v3/COVERAGE.md`, `tasks/answer_bench/REPORT_v0.md`, `SCHEMA_V3.sql` §C/§D,
  `CASE_MAP.jsonl` (joined to `MASTER_BANK.jsonl`): **63 G12 commodity cases**, 8 F&O cases
  (1 `nse_fno_history` + 7 `nse_fno_bhavcopy`), **19 bhavcopy_backfill cases**.
- Held-state probes (read-only, bounded): `mkt_commodity_daily` = 25,255 rows / **13 series** /
  2019-01-01..2026-10-06 / **no `known_at`** column. NSE full bhavcopy 2019-06-27..2026-10-23
  (1,754 dates), NSE old-format 699, BSE 1,937, session calendar 1,927.
- Wrote `reality_engine/scripts/fetch_fo_bhavcopy.py` (legacy + UDiFF URLs, 2019-01-01.., resume
  manifest, `--interval` 0.4, 403/429/503 back-off + Retry-After, NSEClient cookie warm-up every
  200 requests, tidy parser to 16 columns, `--dry-run`, `--parse-only`).
- Wrote `reality_engine/scripts/fetch_eq_bhavcopy_gaps.py` (date gaps from the index-bhavcopy
  calendar vs 4 bhavcopy tables, name gaps across both NSE tables, `--names`, `--dry-run`;
  downloads delegated to the existing `fetch_market_raw.Source` classes via `only=`).
- Wrote `reality_engine/scripts/fetch_commodity_series.py` (World Bank pink sheet through the
  existing `factor_loaders` parser with 24 G12 matchers, FRED public CSV ×4, RBI reference-rate
  archive ×1 POST/month; `known_at` per source; `--dry-run`).
- Tests: `reality_engine/tests/test_missing_series_fetchers.py` — **25 tests, OK**, fixtures in
  `reality_engine/tests/fixtures/missing_series/`.

## Findings the controller needs

1. **Equity bhavcopy date gaps: 0.** Every calendar session 2019-01-01..2026-10-23 already has a
   raw bhavcopy row in one of the four tables. The only "missing" dates are two weekend rows in
   `mkt_nse_index_daily` (2023-06-04, 2023-11-04) — spurious calendar rows, not sessions.
   NSE name-level gaps: **0** after checking both NSE bhavcopy tables.
2. The 19 `bhavcopy_backfill` cases are therefore **not a fetch problem**. Probed cause: ETF
   symbols (QGOLDHALF, QNIFTY, NIFTYBETF, MONQ50, NIF100IETF) are **absent from
   `symbol_isin_history`** (so RESOLVE cannot bind them) while their prices *are* held in
   `mkt_nse_full_daily`; and the derived `daily_price_delivery` — the table the SERIES planner
   reads — is thin for them (QNIFTY 331 rows vs 1,696 held; NIFTYBETF 125 vs 679).
   Both are build/mapping fixes over held data.
3. F&O estimate: 2,042 sessions → 2,042 requests, 23.8 min p50 / 64.7 min p95 at 0.4 s.
4. Commodity estimate: 328 requests (2 pink + 4 FRED + 322 RBI months), 10.9 / 38.3 min.

## Next

- Controller runs the fetches (commands in the report); nothing here needs a schema change.
- Then build `commodity_price_daily` / `fno_oi_daily` from the raw files (loaders not in scope).
