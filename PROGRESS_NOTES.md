# T-242 xbrl annual extension (dsh DeepSeek)

- 18:00 IST: `xbrl_crosscheck.py` now loads `fin_annual_line` beside `fin_quarter_xbrl`; BS as-at, H1/FY/Q durations,
  CF sign-free, cash closing-balance alternative, per-row verdict merge, reported-only contradictions; 10 tests pass.
- 17:56 run: results 2,812 verdicts (2,435 match, 13 sign-convention, 132 unit fix, 232 contradict); AR 0 (no FY line
  for its symbols). Seed-7 annual contradictions 15/20 real -> not installed; evidence
  `tasks/t242_xbrl_annual_measure.md`.
- Next: normalise store `other_expenses` / `total_equity` / `equity_share_capital`, then re-judge and install.
