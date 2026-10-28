# PROGRESS_NOTES

- 2026-10-28 ~T+0: read context pack + PILOT_SPEC + SCHEMA_V3 §B/§C; probed the held stores
  (truth DuckDB snapshot is at `data/snapshots/truth_2026-10-19.duckdb`, not the data root).
  Confirmed: px_daily 7.26M rows, price_bands raw 1,683 sec_list files, index_history 446
  notices / 444 PDFs, results_facts has all 22 mapped concepts, ar_facts segment facts parseable,
  shp_index 50,838 rows. Wrote `reality_engine/pilot/build_t1.py`.
- ~T+60m: offline unittest `reality_engine.tests.test_pilot_t1` green (21 tests). Fixed schema
  statement extraction (comment stripping), bank universe from MASTER_BANK entities (488 ISINs),
  shares_out from XBRL paid-up/face value (facts carry period_end, not instant), DataFrame `.isin`
  shadowing, working-capital balance-sheet items are instant facts.
- ~T+150m: full pilot build green (321 s wall): 738,113 daily rows, 619 membership intervals,
  507,064 event_day0, 909,967 leakage rows, 198,458 metric rows, 8,154 segment rows. Fixed
  leakage ret_pct/delivery_z (DataFrame.get on a MultiIndex returned nothing -> dict lookup),
  metric-series PK dedupe, instant-vs-duration balance-sheet preference.
- ~T+190m: `--checks` green: 152/153 hand checks (99.3%), Nifty 50 = 50/50/50 on three dates,
  32/33 notice flips (one stale-symbol ISIN fallback, documented), all index shapes <= 1.11 ms.
  `tasks/pilot_t1/CHECKS.md` written. Idempotent: a second build reproduces identical counts.
  DONE. Open: full-universe run (est. 45-60 min) is the same code with `--universe all`.
