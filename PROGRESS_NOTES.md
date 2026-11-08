# T-129 progress

- Read context pack and the four code/test files; pointed at the actual pilot10 DB through reality-data (6043 kpi rows).
- Rule A implemented in `doc_default_period` via `_ytd_default` (YTD span → H1/9M/X quarter; Q4 keeps FY); fixed a 6M fallback defect.
- Rule B: `derive_quarters` (Q2=H1-Q1, Q3=9M-H1, Q4=FY-9M; flow metric whitelist; 1% pin; quarantine-aware; `derived_cumulative_v1`, is_reported 0, quote "FY26 242.7 - 9MFY26 185.2").
- Rule C: `check_source_scale` + `source_scale_mismatch` fail code; MARUTI-127 pair tested.
- Tests: 134 passed over the three listed test files with the sandbox 0o700 workaround; the literal command hits 6 pre-existing tmp_path sandbox errors.
- Next: after-vs-control kpi builds on `.tmp/p10.db` / `.tmp/p10_noa.db`, then `--part checks`, row_check verdict counts, number-check replay (MARUTI-127 only), docs 9j + STATE.
- Blockers: sandbox denies listing dirs created with mode 0o700 (pytest tmp_path), workaround patched in-process for verification only.
