# Task 02b — drive_fetch: find a file on Drive when its date prefix differs

Context: `reality_engine/toolbelt/drive_fetch.py` (merged on main in 8845232; read it and `reality_engine/toolbelt/README.md`).
Stored PDFs are named `<YYYYMMDD>_<hash8>_<rest>.pdf`; the date prefix is the crawl date and drifts between the DB,
local disk and Drive. Live example (read-only):
- DB `ar_docs` path: `.../pdfs/20MICRONS/ANNUAL_REPORT/20261010_9041611d_4be8a863-82ec-4642-82c2-b0bd10618a7a.pdf`
- Drive (`gdrive:InfoDiffusion_archive/pdfs/20MICRONS/ANNUAL_REPORT/`): `20260828_9041611d_4be8a863-...pdf`
- `drive_fetch --dry-run <DB path>` → `missing` today. It should be `present` with `matched_by: "hash_suffix"` and the real remote path.

## Do
1. When the exact remote path is absent, look in the same remote folder (from the cached index; refresh that folder
   only if the index lacks it) for names whose `_<hash8>_<rest>` suffix equals the requested one. One match → use it
   (`matched_by: "hash_suffix"`); several → pick the newest date prefix and list the others under `alternates`; none →
   `missing` as now. Exact-path matches report `matched_by: "exact"`.
2. Downloads keep the requested local filename unless `--keep-remote-name`.
3. Tests in `reality_engine/tests/test_toolbelt.py` with the existing fake-rclone stub: exact, one suffix match,
   several matches, none.

## Acceptance checks
1. `python -m unittest reality_engine.tests.test_toolbelt` passes (22 + yours).
2. Live: `python -m reality_engine.toolbelt.drive_fetch --dry-run "C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\pdfs\20MICRONS\ANNUAL_REPORT\20261010_9041611d_4be8a863-82ec-4642-82c2-b0bd10618a7a.pdf"`
   → present, matched_by hash_suffix, remote name starting `20260828_9041611d_`.
3. Only `drive_fetch.py`, its README row and `test_toolbelt.py` change. No writes to live DBs or data folders.

Report format: `tasks/optimizations/00_SHARED_CONTEXT.md` "Report format".
