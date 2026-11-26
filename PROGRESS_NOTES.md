# T-242 run_ledger incremental ingest

- 26 Nov 06:2x: added `ingest_offset` (path,size,offset,mtime,state), `_prior`/`_read_since`/`_save_pos`; `ingest_claude` and `ingest_dsh` now merge only appended complete lines. 4 new tests (tail-only spy, full-vs-incremental equality incl. chunk-split tool_use/result, shrink reset, dsh events). 8/8 pass in `test_run_ledger.py`, typecheck clean. Docs: `docs/DEVELOPER_GUIDE.md` s7, `tasks/STATE.md`.
- Next: controller merges; nothing else pending.
- Blocker (environment, not code): under this dsh workspace-write sandbox a directory created with mode 0o700 cannot be listed, so pytest's `tmp_path` basetemp fails at setup for every test using `tmp_path`. Verification ran with a fresh `PYTEST_DEBUG_TEMPROOT` plus a one-off `Path.mkdir` mode drop; the bare accept command needs an unconfined run or a sandbox fix.
