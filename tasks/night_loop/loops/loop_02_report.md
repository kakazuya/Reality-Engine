# Loop 2 report (session 02, Eagle, 4 Nov 2026; times are this machine's clock)

## Status: in progress

## Store gaps (done except snapshot)
- Fetched 19 Oct-4 Nov into normal places with existing fetchers (`D:\RealityEngine\pilot10\scratch\store_gaps.sh`, log `pilot10\logs\store_gaps.log`): NSE/BSE bhavcopy, delivery, bulk/block, insider, corp actions, indices; loaded; `build_bulk_block_deals` 1,748 rows upserted.
- `shp_index` now has Sep 2026 for all 10. SHP XBRL for the window: 51 files, 28 new, in `D:\RealityEngine\raw\nse_shp_xbrl_pilot` (`scratch\fetch_shp10.py`).
- **Finding:** shareholding filings carry old ISINs for 5 of 10 companies (BAJFINANCE INE296A01016, HINDALCO IN9038A01010, HDFCBANK INE040A01018, INFY IN9009A01011, SUNPHARMA INE044A01010), absent from `symbol_isin_history`. An ISIN filter returned nothing. Added to `pilot10_profile.json`.
- **Finding:** `build_truth_snapshot` failed: `raw_market/masters` absent on this laptop (raw_market archived as 7z on `gdrive:InfoDiffusion_archive/raw_market`). Restored masters and corpact folders from the archive with skip-existing. The failed attempt's 12 KB `.building` file was removed.
