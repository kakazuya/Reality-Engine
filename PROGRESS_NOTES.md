# T-242 progress notes

- 26 Nov: tx statement gate (ckpt_0014 J/P) implemented in `reality_engine/v2/obs_speaker.py` (call logistics,
  deferral-only passages and forward-pointer fillers dropped; `attach_statement_speakers(..., call_period=...)` anchors
  a prepared remark's "this quarter"/"the year"/"half year"/"previous year") and wired through the three call sites in
  `reality_engine/v2/observations.py`. Measured on a copy of `hy4_out/obs_transcripts_394_v3.db`: 48 of 125,880
  statements dropped (0.04%), 9,571 anchored, all 4 J rows dropped, all 4 P rows anchored, 0 of 132 graded R rows
  dropped or changed. Tests: `test_obs_speaker.py` 57 passed (3 `tmp_path` tests blocked at setup by a sandbox
  ACL bug: python cannot list a directory it just created), `test_observations.py` 176 passed. Docs:
  `docs/DEVELOPER_GUIDE.md`, `tasks/STATE.md`, `tasks/t242_statement_gate_measure.md`. Next: typecheck, report.
