# T-238 gap 1 brief: read the OCR-routed pages (hy4 never reads them today)

Ticket: T-238 (Shivam 22 Nov 2026). Reviewer: Wolf (Opus).

Goal: the T-237 Opus deep read of SOMANYCERA found hy4 read only 56 of its 172 deck pages. 72 of the skipped pages are
routed `needs_ocr` ("text layer jumbled: label-dictionary share < 0.75" or "no OCR words yet"); Opus read 2,005 numbers
on them from the page images. Across stores: 91-company set (`D:/RealityEngine/tg_build/measure10`) deck pages
needs_ocr 5,338 vs table_or_chart 4,702 (+ AR needs_ocr 2,853); 394-company set (`.../decks403`) deck needs_ocr 35,311 vs
30,802 read. On the pages both read, hy4 and Opus agree on 2,155 values (Opus 11 extra, hy4 207 extra), so the reader
is fine; the router drops half the figure pages.

Evidence:
- `D:/RealityEngine/tg_build/measure10/c48/routes.csv` (route + reason per page) and `c48_ocr.db` table `ocr_page`
  (symbol, doc_key, page, doc_type, known_at, text, words_json, ocr_conf): RapidOCR already holds all 72 skipped
  SOMANYCERA deck pages. `reality_engine/pilot3/build.py` `--part ocr` (T-121) writes `<stem>_ocr.db`.
- `reality_engine/v2/page_route.py` (routes), `reality_engine/v2/observations.py` (reader; `OCR_READER` hook at
  ~line 2897 for Kilo Dots, which is gone - 404), `reality_engine/scripts/tg_measure_build.py` (`--parts`).
- decks403 stores were built with `--parts registry,pages` only: no `_ocr.db` yet.
- Opus facts for comparison: `D:/RealityEngine/t237/opus_facts.db` (table fact, symbol SOMANYCERA).

Steps:
1. Route: a `needs_ocr` page whose `<stem>_ocr.db` holds OCR words is re-routed on those words with the same rules
   (table_or_chart / no_figures / text_ok); keep the original reason and add `word_source='rapidocr'`.
2. Reader: for such pages `observations.py` sends the page image + the OCR text layer to hy4, and every script check
   (value in text layer, axis/label/period/basis) runs against the OCR words, rows carrying `text_source='ocr'`. No
   Dots call; drop the dead Kilo Dots default (keep the env hook).
3. Build: make `tg_measure_build --parts ocr` work for the decks403 stores (resumable, CPU, `--ocr-max-seconds`); say
   pages/second measured on 20 pages and the projected time for 35k pages at 4 processes.
4. Scoped test (model calls allowed, hy4 only, cap 600 pages): SOMANYCERA's 72 pages + 300 random needs_ocr deck pages
   of the 91 set into a copy of `D:/RealityEngine/t230/obs_91_i.db` with `--only`; regress (gate 0 newly broken);
   compare SOMANYCERA numbers against opus_facts on those 72 pages (value overlap, measure agreement); status mix
   verified/unverified/quarantined of the new rows vs table_or_chart rows.
5. Tests (synthetic OCR db) for re-route and OCR-text checks; docs: V2_SCHEMA_CONTRACT section 17 (T-238), DEVELOPER_GUIDE.

Files: `reality_engine/v2/page_route.py`, `reality_engine/v2/observations.py`, `reality_engine/scripts/tg_measure_build.py`,
`reality_engine/pilot3/build.py` (only if the ocr part needs a hook), tests, the two docs. Do not edit tasks/STATE.md.

Pitfalls: a deck reader job (`.tmp/t232read/loop2.sh`) appends to `.tmp/t232read/obs_decks394.db` in the main
checkout all day: never write it; do not run the 35k-page OCR yourself (report the command, Wolf runs it); RapidOCR is
CPU heavy - one process in your tests; OCR text often splits numbers ("1,2 34") - verify by digits-only match the way
the text-layer check already does and report how many values verify.

Accept: tests pass; typecheck clean; regress gate 0 newly broken; report under 20 lines: re-route counts, the 72-page
comparison vs Opus, status mix, OCR speed and projected run time.

Stop if: OCR-text verification passes under 50% of values that Opus also found (report examples).

Budget: about 3 hours, DeepSeek max effort.
