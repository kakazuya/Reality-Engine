# T-209 progress (Eagle worktree 2026-11-13T18:27Z)

## Measurement (before any fetch)
- `shp_index` quarter_end >= 2024-04-01: **27,360 filings / 2,991 ISINs**, every row with an XBRL link and a broadcast_at.
- Local raw SHP XBRL already held: **797** gz files in `D:/RealityEngine/raw/nse_shp_xbrl_pilot` (0.01 GB). Drive holds only that same pilot folder (`gdrive:InfoDiffusion_archive/msi_raw/raw/nse_shp_xbrl_pilot`, 797 files); no universe SHP folder exists on Drive. ~26.5k files to fetch into `D:/RealityEngine/raw/nse_shp_xbrl_universe`.
- `results_xbrl.db` (read-only): **42,254 ok filings since 2024-04-01 / 3,548 ISINs**. The half-year statement of assets and liabilities IS held: filings with an equity fact at their own period end: 2024-09-30 **4,157**, 2025-03-31 **5,147**, 2025-09-30 **5,405**, 2026-03-31 **5,963**, 2026-09-30 **509** (in progress), other quarter-ends <= 36. Concepts: `Equity` (INDAS, 18,264 filings), `ShareholdersFunds` (INTEGRATED, 3,076), `LongTermBorrowings`/`ShortTermBorrowings` (3,013), `Borrowings` (1,594), `CashAndCashEquivalents` (21,277), `Assets` (21,235). No new endpoint needed for (b).
- NSE fetch smoke test (5 URLs, UA + Referer): **5/5 ok**, 0.36-3.38 s per file, 196 KB-1.2 MB each.
- Blue Star 2024-06-30 raw file known answer: promoter 36.52 %, public 63.48 %, FII 17.05 %, MF 21.60 %, insurance 1.57 %, government 0.00 %, pledge 0.00 %; XBRL ISIN INE472A01039, index row ISIN INE472A01021 (ISIN change; store keeps both).

## Next
- `reality_engine/structured/universe_build.py`: threaded resumable fetch, parse via `pilot3.stores.parse_shp_xbrl`, balance sheet from `results_xbrl.db`, coverage.csv + sample20.csv.
- Then full fetch (background), tests, docs.

## Update 00:20 IST
- Module + tests written; `test_structured_universe.py` + `test_pilot3_shp_holder.py`: 10 passed; typecheck clean.
- Balance-sheet layer built into the real store: 41,931 of 42,254 ok results filings processed, 21,069 carry total equity, 125,564 rows (323 filings skipped: no broadcast/dissem/filing timestamp). Spot-checked MONOLITH and CRISIL by hand.
- SHP raw fetch: 11,271/27,360 gz files on disk in `D:/RealityEngine/raw/nse_shp_xbrl_universe` (pooled sessions, 8 threads, throttled to ~6 req/s; 2 failures so far). Parser dry-run on 400 real filings: 400 ok, 2,794 category rows, 97 filings with a non-zero pledge (basis `of_promoter_holding`), 297 zero.
- Next: finish fetch, parse all, rerun balance, report CSVs, docs, DATA_INVENTORY.

## Final 01:10 IST
- Store built: `D:/RealityEngine/structured/structured_universe.db` (~150 MB). SHP: 27,306/27,360 filings parsed ok (1 corrupt XML at source, 27 NSE 404s, 26 placeholder `.../-` links, all recorded as pending/unusable); 149,155 `shp_category` rows over 3,060 ISINs, 26,999 `shp_pledge` rows. Balance sheet: 125,564 rows over 21,433 results filings (41,931 seen; 323 skipped for no broadcast timestamp). Raw cache 27,307 gz files, 0.28 GB (`D:/RealityEngine/raw/nse_shp_xbrl_universe`).
- `coverage.csv` 734 rows (per period, companies with a row / with a filing), `sample20.csv` 20 rows (seed 20261113, all three tables), `report.md`. Tests: 10 passed (ticket command), 17 passed + 1 skip including the v4 pilot parser tests; typecheck clean; accept command exit 0.
- Docs: DEVELOPER_GUIDE O19c, RAW_DATA_FAMILIES row, T-207 section 11, MSI_LAPTOP section, STATE.md, DATA_INVENTORY regenerated.
- Note for the controller: the worktree's `reality_engine/data/` holds fixtures only, so `python -m reality_engine.scripts.data_inventory` cannot run unmodified in a worktree; I ran it with `di.DATA` pointed at the main checkout's data root. Worth teaching the generator `REALITY_DATA_ROOT` (not changed here).


