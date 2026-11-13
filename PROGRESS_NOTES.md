# T-207 progress

- 2026-11-13 17:25 IST: module + 8 tests done (30 passed with T-118), panel reproduces T-118 (max diff 0.0005), full run 245 s, sector merge and BH denominator fixed; doc `docs/research/T-207_factor_rewards.md` written, T-118/guide/STATE updated. Next: final acceptance run, then report. No blockers.
- 2026-11-13 17:55 IST: final run 249 s, 30 tests passed, 280 claims / 264 BH survivors, outputs written; typecheck run; doc final. Ready to report.
- 2026-11-13 19:05 IST: round 2 (decomposition, block-balanced, PERSISTENT, cross/staleness, placebo) added; 33 tests pass; main 261 s, --placebo 520 s (placebo 257 s); 24m loss is block-sign + staleness, not collinearity; doc sections R2.1-R2.7 written. Ready to report.
