# Progress — Reddit question mining

- 2026-10-28 16:2x: context pack read; raw inventory confirmed (778,501 posts across
  28 non-empty subreddits; 4 empty files skipped). Mining script written; first two
  runs killed for speed, third (title-first) completed.
- 200-row bank authored (75 Indian / 75 international / 50 technical), validator
  passes, acceptance command prints `ok`.
- Next: rerun with NEW:* family mapping, then aliases.csv, leak check, REPORT.md.
- Blocker: DSH_WORKER_PROGRESS_NOTES is unset in this worker, so this file lives in
  the job's output directory instead.
- 2026-10-28 resumed: re-ran mine.py (NEW:* families now land: position_decision
  7,389, technical_setup 5,789), aliases.csv written (48 aliases, 13 not resolving),
  REPORT.md rendered (570 lines), leak check now also scans post bodies for a
  15-word verbatim run: 778,501 posts, 0 hits. Added 5 international-value patterns
  to patterns.csv (second_order_macro, sum_of_parts_holdco, dividend_sustainability,
  customer_supplier_concentration, thesis_break_sell) so every bank reddit_pattern
  has a counted row; re-mining now, then final report + leak rerun.
- 2026-10-28 done: mine rerun (778,501 posts; 116,822 kept; 48 patterns), REPORT.md
  570 lines, aliases.csv 48 rows (13 unresolved), bank 200 rows (75/75/50) passes
  the acceptance command, final leak check 0 hits at 10-word title and 15-word
  body granularity. All four acceptance checks met; nothing left open.
- 2026-10-28 review follow-up (worker): the reviewer found 13 of 48 patterns with
  zero rows. 11 in scope now carry 43 rows in bank_gap.py (5 each for
  fno_vs_cash_flow, global_cue_overnight, dividend_record_date,
  penny_low_price_stock, macro_event_what_if; 3 each for ta_chart_pattern,
  theme_proxy_play, merger_arbitrage, ipo_vs_listed_peer,
  second_order_beneficiary, results_calendar); bank rebuilt to 243 rows
  (75/75/50/43). `mf_etf_vs_stock` and `broker_platform_process` are recorded
  out of scope in REPORT.md §4. Leak check clean. Next: rebuild the master bank
  and check the thin family x level cells.
- 2026-10-28 follow-up done: master bank rebuilt 1030 -> 1073 cases (1432 case x
  family pairs); `--check` all PASS. Family 10: 10 -> 19 cases and 1 -> 5 levels
  (stock 15, sector/index/market-cap/price-band 1 each). Price-band level: 1 -> 6
  cases. Thin family x level cells 137 -> 134; 3D grid empty 610 -> 585. Leak
  check 0 hits at 10-word title and 15-word body granularity. Nothing open.
