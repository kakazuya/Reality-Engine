# Task G0 — all raw data goes to the D drive

## Goal
Every fetcher writes raw source files (PDFs, bhavcopies, API dumps, downloads) under one D-drive root. A migration
script moves the raw files now on C there safely. C keeps only code, logs and the processed databases.

## Why
Shivam's rule (2026-10-25): raw data on D, C for operations and the main DBs. These raw folders sit on C today:

| folder under `reality_engine/data/` | size | files |
|---|---|---|
| `pdfs` | 15.5 GB | 1,538 |
| `raw_market` | 13 MB | 304 |
| `bhavcopy`, `tax_sources`, `ar_queue`, `hotline`, `index_constituents` | small | — |

D has 576 GB free, and `D:\RealityEngine\pdfs` already exists.

## Files to touch
- `reality_engine/config.py`:
  - add `RAW_ROOT = Path(os.environ.get("REALITY_RAW_ROOT", r"D:\RealityEngine\raw"))`;
  - add one helper, `raw_dir(source) -> Path`, which creates the folder;
  - keep the existing names working.
- Every fetcher that writes raw files, and every reader that loads them, switches to the helper.
  - Find them with `grep -rn "raw_market\|\"pdfs\"\|bhavcopy" reality_engine analysis`.
  - At least: `reality_engine/scripts/fetch_market_raw.py`, `fetch_etf_nav.py`, `fetch_nse_api_raw.py`, and the
    BSE/deck/AR/concall downloaders.
- New: `reality_engine/scripts/migrate_raw_to_d.py`.
  - Dry run by default.
  - `--apply` copies each file to `RAW_ROOT/<folder>/...`, verifies size + sha256, then deletes the C copy.
  - It writes a JSON manifest to `RAW_ROOT/_migration/<date>.json`.
  - It is resumable and skips files already verified.
  - For `pdfs`, reuse `D:\RealityEngine\pdfs` when it holds the same file (same sha256).
- New tests: `reality_engine/tests/test_raw_root.py` (temp dirs only).
- Do not touch: any database file. DB paths stay on C.

## Steps
1. Map every raw write and read path. Report the list.
2. Add the helper, then switch the fetchers and readers.
3. Write the migration script and its tests.
4. Dry-run it against the real folders (read-only). Report counts and bytes per folder, and how many are already on D.

## Acceptance checks
1. `python -m unittest reality_engine.tests.test_raw_root` passes. The full suite has no new failures versus main;
   list any that also fail on main.
2. `grep` shows no fetcher still writing raw files under `reality_engine/data/`.
3. The dry-run report lists every folder with its file count, bytes, and how many are already on D.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_raw_root
```

## Budget
≤ 20 tool calls before the first edit; ≤ 90 total; $0 paid. Do not run `--apply`: Claude runs it after review.

## Report format
1. What changed  2. Path map (writer → new location)  3. Dry-run numbers  4. Open problems  5. Tool calls before first edit / total.
