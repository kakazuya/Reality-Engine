# T-121: every page gets text, and a canary proves extraction holds on any company, type and year

Ticket: T-121

Goal: (1) a profile build never leaves a page without text: pages with no text layer are OCR'd inside the build and
feed the extractors; (2) a fixed, stratified canary set of documents from companies the extractors never saw, across
document types and years, measures text coverage, OCR confidence, number reading and extractor yield on every run, so a
change in a company's document format shows up as a drop, not as silently missing rows (Shivam, 8 Nov).

Files (only these): `reality_engine/pilot3/build.py` (a new part `ocr` between `pages` and `transcripts`, and in `all`),
`reality_engine/pilot3/registry.py` only if `build_pages` needs the OCR db path from the profile, new
`reality_engine/pilot3/doc_canary.py`, new `reality_engine/tests/test_doc_canary.py` and a test for the `ocr` part,
`docs/DB_BUILD_GUIDELINES.md` (new short section), `docs/DEVELOPER_GUIDE.md` (`--part` list).

Evidence (Opus, 8 Nov):
- A fresh 6-company build (`scratchpad/fresh6/fresh6.db`, read-only) has 28,528 pages, of which 1,720 (6%) have no
  text (`doc_page.method='needs_ocr'`, chars < 50) and 130 documents have no page with text at all. By type: results
  12.6% of pages textless, decks 12.6%, announcements 7.5%, annual reports 1.6%, transcripts 0%. By year: 2019 11.1%,
  2020-21 8.7%, 2022-23 3.8%, 2025-26 1.4% (older filings are scanned more often).
- OCR exists but is not in the build: `reality_engine/pilot3/ocr.py` (RapidOCR ONNX, CPU; `python -m
  reality_engine.pilot3.ocr --out <ocr.db> --pages-db <pages.db> --symbols ...`) writes `ocr_page`; `build.py
  --ocr-db <ocr.db>` then fills `doc_page` and the extractors read those pages (`build.extract(..., ocr_dbs)`). A
  profile build passes no `--ocr-db`, so the 6% is dropped. Opus is running ocr.py on the fresh6 pages now
  (`scratchpad/fresh6/ocr.db`, log `ocr.log`): use its throughput and confidence numbers when it finishes.
- Older OCR accuracy work: T-020 / T-040 (TextRecognizer on the HP was more accurate on numbers; RapidOCR on CPU is the
  default here). Do not change the OCR engine in this ticket.
- Raw files live on Drive; `reality_engine/raw_store.py` fetches them on demand (`RawStore.local`, `prefetch`). A
  profile's `raw_root` must be `D:/RealityEngine/raw` for Drive fetches to resolve.

Steps:
1. Part `ocr`: reads the profile (pages_db, symbols), runs `ocr.run` for the build's needs_ocr pages into
   `<out dir>/<name>_ocr.db` (resumable, `--max-seconds` respected), then the `pages` fill uses it; `all` includes it.
   Test on a tiny fixture with one scanned page (render a PNG-only PDF with PyMuPDF) that the page ends with text
   and method `ocr_rapid`.
2. Canary: `doc_canary.py --out <dir> [--per-cell 3] [--seed S]` picks documents from the pilot60_history manifest
   (`D:/RealityEngine/raw/pilot60_history/manifest.csv`, via raw_store) for companies NOT in any pilot profile, one
   cell per doc type x filing year (2019-2026), `--per-cell` documents per cell, fixed seed so the set is stable; it
   runs the same text read (`docs_collect._extract`), OCR for textless pages, and the KPI extractor's page reader on
   them, and writes `canary.csv` (doc, type, year, pages, text pages %, OCR pages, mean OCR conf, numbers read per
   page, kpi rows per doc) plus a summary by type x year. A second run compares with the previous summary and prints
   any cell whose text coverage or rows per doc fell by more than 20%.
3. Run the canary once with `--per-cell 3`; report the table; name the worst cells.
4. Docs. Final answer starts with `Docs updated:`.

Accept: the new tests pass; the canary run finishes and its table covers every doc type x year with documents.
Limits: never write to `D:/RealityEngine/pilot10/pilot10.db` or other live dbs; outputs under `.tmp/`; no model calls;
OCR on CPU only, at most 2 OCR processes; `PYTHONIOENCODING=utf-8`; pytest `tmp_path` is unusable in the sandbox
(shadow it with a `.tmp` fixture like the other tests); the controller applies your diff.
Budget: 130 tool calls, 2.5 hours.
Stop if: ocr.py cannot read a Drive-only PDF through raw_store: report the error and stop.
