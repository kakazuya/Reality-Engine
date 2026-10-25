# Task G0 — raw data to the D drive

- 2026-10-25: path map done. `config.RAW_ROOT` + `raw_dir()` added; `BHAVCOPY_DIR`/`PDFS_DIR`/
  `MACRO_PDFS_DIR` now default under D (`PDFS_DIR` reuses `D:\RealityEngine\pdfs`). 31 fetchers/readers
  switched to `raw_dir()`; docstrings updated. `migrate_raw_to_d.py` + `test_raw_root.py` written
  (8 tests pass). Dry run: 3,324 files / 16.4 GB, 68 pdfs already on D by sha256.
- Next: baseline suite comparison (changes backed up in `_g0_backup/`, restored afterwards), final report.
- Blocker: this box's `tempfile.mkdtemp` dirs are ACL-locked under the DSH sandbox (WinError 5) and
  `git` cannot write its index (git dir outside the sandbox), so the suite errors en masse here.
  Both are pre-existing and reproduced on a pristine HEAD tree — see `_baseline_suite.txt`.
- 2026-10-25 (final): 34 files changed (31 path switches + config + 2 new files). `test_raw_root` 8/8 OK.
  Suite vs pristine HEAD: HEAD 1321 tests / 17F+415E; mine 1329 tests / 17F+416E; the only set-difference
  tests pass individually (10 s CLI-help timeout at 9.4 s, plugin timing) -> no real new failures.
  Dry run: 5,993 files / 16.65 GB, 68 pdfs already on D (content match). Nothing copied or deleted; no --apply.
- Next: Claude reviews and runs `python -m reality_engine.scripts.migrate_raw_to_d --apply` with fetchers stopped.
