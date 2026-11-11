# T-189 step 2: routed page reading (page_route) + image reads + serving the cells

Ticket: T-189
Goal: every page of a pilot3 store's `doc_page` goes to exactly one reading route chosen by scripts, table/chart pages
are read by Dots on the PAGE IMAGE in grid format, and the resulting cells are served to the answerer through the
reality-data MCP (labelled verified / unverified; quarantined never served).

Evidence (measured 11 Nov, 30 hand-read frozen2 pages, `D:/RealityEngine/v2/reference_pages_frozen2/handread/score_local.csv`):
- Dots image grid P 83.8 / R 89.6; Dots on layout text ~62 / ~67. So the image is the input for table/chart pages.
- Every reader invented figures on 2-4 pages that print none (cover letters, intimations, contents, auditor prose):
  such pages must never reach a reader.
- The position check (`v2/reference_geom.py` settle_page) misses many right cells (174 of 264 on 7 pages):
  unverified cells MUST still be served, labelled, or recall collapses.
- Existing code to reuse, not rewrite:
  - `reality_engine/v2/page_words.py` `words_for(store_db, doc_key, page, ocr_dbs)` -> PageWords(source, words,
    quality ok/none/jumbled, reason) (lines 176-219); `quality()` lines 78-98.
  - `reality_engine/v2/page_reader.py`: `select_pages` (31-61), `is_table_page` (64-78), `_chart_like` (81-96),
    `read_page` (108-254: today sends the image only for chart-like pages, else layout text), out db `page_read` /
    `page_cell` (`_create_out_db` 257-276), run ledger `_ledger` (303-325), `main` (328-397).
  - `reality_engine/v2/reference_pages.py`: `_model_call(reader, prompt, image_b64)` 324, `GRID_PROMPT` 446,
    `parse_grid` 460, `_page_image_b64(store, doc_key, page)` 551; `transcribe --input image --format grid` is how
    the measured Dots image run was made.
  - `reality_engine/pilot3/hp_ocr.py` (`plan --pdf-dir`, `fetch --words-out`, `write_db` 455-491 writes `ocr_page`
    rows that `page_words.ocr_words` reads).
  - Serving: `plugins/reality-data/server/lookups_pilot3.py` (pilot3_* lookups; see `kpi` 245 and `_check_cols` /
    `_visible` 425-460 for how row_check status hides quarantined rows) and `plugins/reality-data/server/server.py`
    (tool registration).

Steps:
1. New module `reality_engine/v2/page_route.py` (scripts only, no model calls). `route_page(store_db, doc_key, page,
   ocr_dbs) -> (route, reason)` with route in exactly one of:
   - `no_figures`: page text has fewer than 4 numbers that are not dates/years/page numbers/phone/PIN/CIN/registration
     codes, OR it is a cover letter / intimation / contents / auditor-report prose page (decide by words such as
     "Dear Sir/Madam", "Sub:", "Pursuant to Regulation", "Table of Contents", "Independent Auditor's Report" together
     with low number density). No reader.
   - `needs_ocr`: `words_for` gives quality `none` or `jumbled` and no OCR words exist yet.
   - `table_or_chart`: `page_reader.is_table_page(words)` or `_chart_like(words)` is true, or the page has images and
     numbers (pymupdf `get_images`).
   - `text_ok`: everything else (prose with a clean text layer); keep the text layer.
   CLI: `python -m reality_engine.v2.page_route --store <db> [--ocr-db <db>...] --out <csv>` writes
   `doc_key,page,doc_type,route,reason,word_source,quality` and prints counts per route and doc_type. A page whose
   OCR words arrive later is re-routed by running the CLI again with `--ocr-db`.
   Add `--needs-ocr-pdf-dir <dir>`: export each `needs_ocr` page as a single-page PDF named `<doc_key>__p<page>.pdf`
   so `hp_ocr.py plan --pdf-dir` can take it (check that `pdf_dir_plan` + `write_db`/`write_words` map the id back to
   doc_key/page; extend `hp_ocr` minimally if not, with a test).
2. `page_reader.py`: add `--routes <csv>` (read only rows with route `table_or_chart`) and `--input image|layout`
   (default `layout`, today's behaviour). With `image`, send the page image (`_page_image_b64`) with `GRID_PROMPT`
   for every page, plus the layout text when words exist; keep the position check and re-ask exactly as now. Count
   unread/failed pages; never drop a page silently: Kilo 502/429 -> retry with backoff (3 tries), then status `error`.
   Add `--into-store`: write `page_read` and `page_cell` into the store db itself (same schema as the out db) so the
   MCP can read them; keep `--out` working.
3. Cell status: `verified` (position check settled it), `unverified` (served, labelled), `quarantined` (never served)
   when the value's digits occur nowhere among the page's words/OCR words, or the page route is `no_figures`.
4. Serving: in `lookups_pilot3.py` add `cells(symbol, terms, period=None, as_of=None, include_unverified=True,
   limit=20)` reading `page_cell` joined to `doc` (known_at <= as_of), matching terms against row_label, col_header and
   table_title (all words, case-insensitive), returning value_text, unit_text, row_label, col_header, table_title,
   status, doc title, doc_type, page, known_at and provenance like `kpi`. Absent table -> `{"found": false, "reason":
   "no page_cell table"}`. Register it in `server.py` as tool `pilot3_cells` with a docstring saying: "figures read
   from table and chart pages (decks, results, annual reports) by the page reader; use when pilot3_fact / fin / kpi
   do not hold the line; status unverified means the position check could not confirm it - say so in the answer".
   Also make `pilot3_fact` fall back to `cells` when it finds nothing (label `source: page_cell`).
5. Tests (new files, run per file): `reality_engine/tests/test_v2_page_route.py` (a synthetic cover letter, a
   contents page, a prose page, a table page, a jumbled page -> each route), additions to
   `reality_engine/tests/test_v2_page_reader.py` for `--routes`/`--input image` (mock `_model_call`, assert retry and
   error counts), and `plugins/reality-data/tests/test_lookups_pilot3.py` cases for `cells` (verified + unverified
   served, quarantined hidden, as_of drops later rows).
6. Smoke run on a COPY of `D:/RealityEngine/n10/n10.db` placed in your worktree `.tmp/` (never write the original):
   route all pages (report counts), then read 6 `table_or_chart` pages with
   `--reader dots-studio/dots-3-note-preview:free@kilo2 --input image --into-store`, and call `cells` on one figure you
   can see on one of those pages. Report pages/min and per-page seconds.
7. Docs: add a section 15 "Routed page reading (T-189)" to `docs/V2_SCHEMA_CONTRACT.md` (routes, rules, CLI, statuses,
   the `pilot3_cells` tool) and name the new tool in `plugins/reality-data/README.md` if that file lists tools.

Files: reality_engine/v2/page_route.py (new), reality_engine/v2/page_reader.py, reality_engine/pilot3/hp_ocr.py (only
if step 1 needs it), plugins/reality-data/server/lookups_pilot3.py, plugins/reality-data/server/server.py, the three
test files above, docs/V2_SCHEMA_CONTRACT.md, plugins/reality-data/README.md.
Accept: python -m pytest -p no:cacheprovider reality_engine/tests/test_v2_page_route.py -q ; python -m pytest -p no:cacheprovider reality_engine/tests/test_v2_page_reader.py -q ; python -m pytest -p no:cacheprovider plugins/reality-data/tests/test_lookups_pilot3.py -q ; basedpyright 0 errors on changed .py files (code-tools typecheck).
Stop if: you need to open anything under D:/RealityEngine/aurobindo/questions/ or D:/RealityEngine/aurobindo/truth/
(NEVER open them); a test outside your files breaks and the fix is outside your files (report it); Dots fails 3
pages in a row in the smoke run (report, do not switch models); any write to an original store under
D:/RealityEngine/.
Budget: 250 tool calls, 3 hours. Run tests per file (RAM ~16 GB, one heavy job at a time).
Limits: free models only (Dots @kilo2); no paid calls; no new dependencies; no edits to row_checks.py or the build
parts; no per-company rules (no symbol names in code).
