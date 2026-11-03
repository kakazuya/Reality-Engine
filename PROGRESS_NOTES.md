# T-056 progress

- 2026-11-04: read brief + context pack; new `reality_engine/pilot3/profile.py` (Profile/ProfileCompany, load,
  active profile + `--symbols` scope helpers); threaded it through build/registry/stores/ratios/statements/kpi/
  transcripts/guidance/call_dates/docs_collect (manifest mode, `collect_manifest`) and
  `plugins/reality-data/server/lookups_pilot3.py` (`pilot_symbols()`: the db's `company` table when
  REALITY_PILOT3_DB is set).
- New test file `reality_engine/tests/test_pilot3_profile.py`: 6 passed (load, no-profile defaults, manifest ->
  pages -> registry/pages/kpi/transcripts/guidance with a nonexistent sandbox root, window filter, --symbols
  scoping, MCP lookups on a REALITY_PILOT3_DB database).
- Accepts: (1) checkpages 145 found (29/78, 59/113, 57/123). (2) KEC `build --part kpi` on a copy: 6,915 rows,
  same multiset, 95-159 s (needs the four --ocr-db databases; without them the 39 OCR rows are absent, as in the
  live db's own build). (3) MARUTI pilot10: docs_collect 147 docs / 1,170 pages 17 s; build registry 0.2 s,
  pages 0.5 s, stores 15.5 s, kpi 11.8 s, transcripts 0.3 s, guidance 0.4 s; company 1 row, doc 147 dated,
  fin_quarter_xbrl 164 (min period_end 2025-12-31), fin_annual_line 260, price_delivery 516 (min 2025-10-01),
  shp_category 180, kpi_series 161; transcript_statement/guidance 0 because MARUTI's 5 concall filings are
  1-page cover letters. (4) real p10 db: MARUTI resolves by symbol/BSE/ISIN, pilot3_kpi returns rows (capacity 1,
  utilisation 2, revenue 10). (5) every existing pilot3 test file passes one per process; the only errors are the
  sandbox-denied pytest `tmp_path` fixture (core 23 passed + 1 error, kpi 34+6, docs 1+3, ocr 10 errors), as
  recorded in guide O8/O9.
- Docs: blueprint section 9 "Profiles", guide O10, DB_BUILD_GUIDELINES section 9 line, tasks/STATE.md one line.
- No blockers. Controller: run `test_pilot3_core.py -q -m "not slow"` on the host (the tmp_path error is the
  sandbox's); the pilot10 build still needs the controller's own run on `D:\RealityEngine\pilot10`.
