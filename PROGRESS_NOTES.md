# T-205 round 5 progress

- 2026-11-13: union gather (round-3 script net at full quota + plan lookups at their own quota), deterministic
  retries (no period, then terms words), cells-for-fin/fact, page-of-hit for search/statements, `price_rows`
  (previous close, adjusted close, first-to-last return, endpoints for a long range), holding share counts per
  quarter end, per-part all/some/none coverage with retries/derived, reading copy plan-first capped at 60k.
  22 tests pass. Both sets re-running from the plan cache after the price/reading fix.
- 2026-11-13 r10: answer_step.py built (one model call, AST-only calcs, figure/number check, one repair,
  unverified list, coverage not_found/abstained rule, 429 waits, resumable, per-question model/tokens/seconds).
  37 tests pass. Beam phase hit 429s and was stopped; DeepSeek (approved paid) ran Blue Star to 46 answers
  (39 ok, 7 unparseable = 15% > 10% stop), then stopped; Aurobindo not run. Beam answers kept apart.
