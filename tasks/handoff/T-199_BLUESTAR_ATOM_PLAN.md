# T-199: atom design, tested on an unseen company (BLUESTARCO) — plan and hand-off for a fresh session

Ticket: T-199. Owner: Eagle. Written 12 Nov 2026 23:20 IST. Start a fresh session with this file, `tasks/STATE.md`
and `tasks/RULINGS.md` only.

## 1. Why this test, and the rules that bind it
- Aurobindo reached DeepSeek 85.5% / 84.1% (two runs) after three passes over the same 69 questions (T-195); Shivam,
  12 Nov: test the next design on an UNSEEN company, not Aurobindo again, because the Aurobindo score may now be
  overfitted. Pass bar unchanged: >= 92% graded right by blind Opus hand-read (partly is not right).
- T-196 showed the data was held but answers stopped early: tool replies looked complete (fixed by T-197), the row
  checker hid the company's own figure (fixed by T-198), and ~1,850 of 2,134 table/chart pages were never read into
  figures, so answers sat in raw text. The atom design closes that last gap.
- Questions are FROZEN before the build: `D:/RealityEngine/bluestar/questions/questions.csv`, 64 questions (statement 17,
  fact 13, compute 11, list 10, guidance 6, price 4, holding 3; 8 past-dated, rest as_of 2026-11-11), SHA-256
  `37417cbbf583d692aa7596ffa4166f05a1dea94cf5126464da28b04300c43c7c` (decision log 12 Nov 22:05). No fix may be drawn
  from them; no worker or answerer opens `D:/RealityEngine/bluestar/questions/`. Harvest (agy, 55 verified questions,
  11 sources): `questions/harvest.csv`.
- Haiku page reading runs as Claude Code subagent sessions on Shivam's Pro subscription (approved 12 Nov): 8 pages per
  session, under 100k context, Haiku at medium effort. DeepSeek off-peak only. OCR on the HP only, headless.

## 2. Done so far (12 Nov)
- Fetch: `D:/RealityEngine/bluestar/` — profile `bluestar_profile.json` (consumer_durables, 2 ISINs; INE472A01039, BSE
  500067), 267 files from BSE 2024-04-01..2026-11-11 (222 filings, 14 decks, 11 results, 11 transcripts, 5 annual
  reports, 4 audio links; 0 errors), `raw/manifest.csv` (329 rows), `pages.db` (263 docs, 5,749 pages, 233 needs_ocr),
  `shp_xbrl.db` (10 SHP XBRL filings). Scripts `fetch.sh`, `fetch2.sh`, `build.sh`.
- Recipe defect (fixed in T-204, 12 Nov): `fetch_pilot60_history --out` used to write only the shared
  `D:/RealityEngine/raw/pilot60_history/manifest.csv`; it now also writes this run's universe ISINs to `--out`, so
  `raw/manifest.csv` comes from the fetch directly. The first run's workaround was filtering that file by ISIN into
  `bluestar/raw/manifest.csv` before `docs_collect`.
- A first build was started with main code and STOPPED by Shivam's instruction (the build runs in a fresh session):
  `bluestar.db` holds registry, pages, transcripts, kpi, guidance and a partial `stores`. DELETE `bluestar.db*` and
  rebuild from scratch (step 3).

## 3. Steps for the fresh session
1. Wait for T-202 (versioned schema, round 2 job 20261112T173001Z-e88d8f6c) to be reviewed and merged (`store_diff`
   clean). Main then has: T-197 tool replies, T-198 checker, T-201 `store_diff`, T-202 schema version, T-203 routing.
2. Fix the manifest defect (one-line `--out` honour in `fetch_pilot60_history.write_csv`, with a test) or keep the
   documented workaround.
3. Build: `rm D:/RealityEngine/bluestar/bluestar.db*` then `bash D:/RealityEngine/bluestar/build.sh` (parts registry
   pages transcripts kpi guidance stores comparatives preferred ratios segments notes checks events; stops on a failure;
   logs `b_<part>.log`). Check the first written rows' dates against the filing record (known_at rule), then
   `python -m reality_engine.scripts.store_registry --scan D:/RealityEngine --out D:/RealityEngine/stores.json` and confirm
   `p3ask fact symbol=BLUESTARCO metric=revenue period=FY26` routes to `bluestar.db`.
4. Route pages: `reality_engine/v2/page_route.py` (T-189) over `doc_page` -> `no_figures` / `text_ok` / `needs_ocr` /
   `table_or_chart`; write `bluestar/routes.csv`; report counts.
5. OCR: the 233 `needs_ocr` pages on the HP (`reality_engine/pilot3/hp_ocr.py plan/run/fetch`; TextRecognizer
   1.0.1.0 is installed and stays installed; the HP must be unlocked; the 5-page smoke test from T-190 is still owed).
   OCR words feed the router again.
6. Atom design (write the brief first, Opus; DeepSeek builds the table + checker + tools; Haiku reads):
   - One table `page_atom`, one row per printed figure: symbol, isin, doc_key, doc_type, page, known_at, table_title,
     row_label, col_header, period (resolved), basis (consolidated/standalone), unit, scale, value, value_text,
     qualifier/definition (T-198 key), bbox, reader (haiku/dots/script), check_status (row_checks: verified /
     unverified / quarantined), check_reasons, created_at. Added as a numbered migration (T-202).
   - Readers: scripts for prose and clean text-layer tables; Haiku subagent sessions (8 pages, page image + text layer,
     grid output) for `table_or_chart` pages; every atom passes the independent row checker (position check
     `v2/reference_geom.py`, `row_checks.py`); unsure = no atom.
   - Tools: `pilot3_fact`/`pilot3_kpi`/`pilot3_cells`/`topic` read atoms beside the existing tables, with the T-197
     coverage block; the company's printed figure first, derived second (T-198 `company_stated`).
   - Measure before answering: atoms per page type, Haiku pages and sessions used, checker verdict mix, and a seeded
     20-page Opus truth sample (precision/recall), as in T-189 step 3.
7. Answer: DeepSeek x2 runs (variance) + Haiku x1 through the reality-data tools (routing finds `bluestar.db`), one
   answer per question with sources; blind Opus grading (labels shuffled; 3 graders, each grades the same third of
   all sets); score vs 92%; misses by cause; `answer_run_report.py`; report
   `D:/RealityEngine/reports/<date>_bluestar_atom_test.html`. Disclose anything seen or changed during the test.

## 4. Open follow-ups noted on 12 Nov (not blocking)
- Topic reply size: ~15 kB even at limit=2 because the coverage document list is long; shrink it with the limit.
- Coverage lists `page_cell` under both searched and not_searched on a store without a cell table.
- Aurobindo answerer-found defects: `D:/RealityEngine/aurobindo_ab/STORE_DEFECTS_SEEN.md`.
- `pilot3.db` (repo default, 4 Nov) predates T-192 and cannot serve its companies through current code; it is last in
  the store registry.
