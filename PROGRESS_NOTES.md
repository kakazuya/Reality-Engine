# PROGRESS_NOTES — extra input-cost series (WPI / news / IMD)

- 2026-10-29 · Done: `series_common.py`, `fetch_wpi_items.py`, `extract_news_prices.py`,
  `fetch_imd_rainfall.py`, fixtures + `reality_engine/tests/test_extra_series.py`
  (40 tests pass offline); all three `--dry-run`s print request counts and exit 0.
  Next: dry-run numbers into the report, request estimates, source verification for the
  controller's first live probe. Blocker: none in this sandbox (no network by rule);
  `DSH_WORKER_PROGRESS_NOTES` was not set, so this file is at the worktree root.
