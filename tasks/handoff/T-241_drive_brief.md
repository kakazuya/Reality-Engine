# T-241 drive brief: move built companies' raw files and finished stores to Google Drive while the build runs

Goal: the FY27 universe fetch will add about 270 GB of raw PDFs to D: (247 GB free now) and Shivam wants the stores
on Drive by 27 Nov. Write a script that, for each company the follow builder has finished, uploads its store and
moves its raw files to Drive, so D: never runs out and the archive is complete.

Ticket: T-241. Reviewer: Wolf (Opus). DeepSeek max effort.

Evidence:
- Raw files: `D:/RealityEngine/raw/pilot60_history/<SYM>/<bucket>/<newsid>.pdf`; one row per file in the fetch
  manifest database `reality_engine/data/pilot/pilot60_history_manifest.db` table `docs` (isin, symbol_at_time,
  local_path, bytes, sha256, status). Sizes so far: ARs 8.2 MB avg, quarterly results 6.4 MB, material filings
  1.75 MB; about 400 GB in all.
- `reality_engine/scripts/raw_to_drive.py` already does hash -> compare -> upload (rclone, `--checksum`) -> delete
  (only when md5+size are on Drive) into `gdrive:InfoDiffusion_archive/msi_raw/<root>/<rel>`. Reuse it; do not write
  a second uploader.
- Built companies: `D:/RealityEngine/tg_build/universe_fy27/cNN/cNN_measure.json` (queue position NN in
  `universe_fy27.csv`); store `cNN/cNN.db` (+ `pages.db`), median 18.6 MB + 21.5 MB.
- Raw readers fetch from Drive through `reality_engine/raw_store` when a local file is gone, so deleting a local
  raw file after a verified upload is the standing rule (Shivam, 7 Nov).

Steps:
1. `reality_engine/scripts/universe_to_drive.py --root <universe root> [--delete] [--once]`: every poll, list
   companies with a measure json not yet in its own state db (`<root>/to_drive.db`); for each, the raw paths of
   its ISIN from the manifest db; run raw_to_drive's hash/compare/upload on exactly those files (add a
   `--files-from` or path-list option to raw_to_drive if it has none), then delete only with `--delete`.
2. Stores: after a company is built, copy `cNN.db` and `pages.db` (checkpoint WAL first, read-only open with
   `PRAGMA wal_checkpoint` is NOT allowed: copy with sqlite backup API to a temp file) to
   `gdrive:InfoDiffusion_archive/universe_fy27/stores/cNN_<SYM>/`; record md5.
3. Never delete a raw file a running build may still read: only after that company's measure json exists.
4. Tests on a temp root with a fake rclone (no network); docs in DEVELOPER_GUIDE next to raw_to_drive.

Files: the new script, raw_to_drive.py (path-list option only), tests, the guide. Never touch
`Downloads\Telegram Desktop`, personal Downloads folders or `D:\Shivam_Private`. Never print keys or rclone config.

Pitfalls: rclone must run with CREATE_NO_WINDOW and no shell; do not upload `.db-wal/.db-shm`; a failed upload
leaves the local file; deletion only after Drive's md5+size match.

Accept: tests pass; a `--once` dry run (no --delete, no upload: add `--dry-run`) on the real root lists the
companies and byte totals it would move; typecheck 0 errors; report under 20 lines. Do not run a real upload or
delete yourself: Wolf runs it after review.

Stop if: raw_to_drive cannot take a file list without changing its current behaviour.

Budget: about 2 hours.
