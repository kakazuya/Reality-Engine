# T-189 step 2 progress (worker, 2026-11-11/12)

- page_route.py: 4 routes (no_figures / needs_ocr / table_or_chart / text_ok), figures filter (dates/years/pages/phones/PIN/CIN/reg codes), marker pages, 5% image-area rule, CLI + counts, --needs-ocr-pdf-dir export (route_export.csv); hp_ocr.pdf_dir_plan reads the sidecar, write_words gets safe file names and a file column.
- page_reader.py: --routes / --input image / --into-store, 3-try 10/30 s backoff, statuses no_figures/no_table/no_words/error, quarantined cells (value digits absent from the page), pages/min + failed + per-page mean summary.
- page_words.py: open_pdf cache (last 3 docs) -> routing went from 206 to 2,152 pages/min.
- lookups_pilot3.cells + pilot3_cells MCP tool; pilot3_fact falls back to page_cell (route "cells", source page_cell).
- Docs: V2 section 15 (routes/rules/CLI/statuses/tool/smoke), section 12 updated for the new flags, README tool list 16 tools, T-189 handoff plan step 2 marked delivered, STATE.md updated.
- Verified: route tests 7 passed; page_reader tests 5 passed; lookups tests 50 passed 1 skipped; test_pilot3_ocr 12 passed; basedpyright 0 errors on 9 changed files.
- Smoke (11 Nov 23:30-00:00): n10 copy .tmp/n10/n10.db routed 50,799 pages: no_figures 10,335 / needs_ocr 1,657 / table_or_chart 36,425 / text_ok 2,382 in 1,416 s (2,152/min). Dots image on 6 table_or_chart pages: 6/6 read, 0 errors, 180 cells (62 verified, 118 unverified, 0 quarantined), 70.2 s = 5.1 pages/min, 20.6 s/page model time. cells("AUBANK","employees jun") returned verified Employees/Jun'25 53,235 (page 6, FY25 presentation).
- Open: 36,425 table_or_chart pages is 71.7% of n10 (model-cost risk; tighten is_table_page/IMAGE_AREA_SHARE if quotas bite); 1,657 needs_ocr pages await the HP run; pilot3_fact cannot run on the n10 copy (it lacks ratio_panel/fin_annual_line, pre-existing _fact_route behaviour), so the fallback is covered by the fixture test only.
