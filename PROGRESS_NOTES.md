# Progress — price bands + index history

- Sources confirmed live (2026-10-28): price bands = nsearchives sec_list_DDMMYYYY.csv (Symbol,Series,Security Name,Band,Remarks; 2019-12-27 404, 2019-12-30 200, continuous to 2026-10-19). Index changes = niftyindices.com/media one-page press-release index (1,520 PDFs 1998->2026; 446 equity change notices 2019+ after dropping fixed income), plus IndexConstituent/ind_<index>list.csv anchors (6 fetched, exact counts).
- Wrote reality_engine/scripts/fetch_price_bands.py, fetch_index_history.py, reality_engine/tests/test_price_bands_index_history.py. 13 offline tests pass.
- Timed samples into .tmp/: bands 30/30 ok, mean 0.140 s at 3.0 s -> 1.56 h full (1783 weekdays) => 2019 decision. Index: media + 30 PDFs, mean 0.164 s -> 0.40 h full (453 requests) => 2019 decision. Parsed 71,472 band rows and 2,502 index rows (88 indices); Nifty 50 rows spot-checked against known events (UPL->SHRIRAMFIN 2024, HDFC->LTIM/JINDALSTEL 2023, IOC->APOLLOHOSP 2022).
- Band CSVs cross-checked against live price_bands on 10 overlapping dates: symbol x series sets identical, all band values agree after "No Band" -> NULL normalisation.
- Done. No DB writes, no commits. Open: sec_list has no ISIN (resolve later); sibling-index note lines ("above changes also apply to X") are not replicated; index rebuild itself not built (plan in report).
