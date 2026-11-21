# T-232 brief: minimal deck stores for the non-91 Telegram companies

Ticket: T-232 (Shivam 21 Nov 2026). Reviewer: Wolf (Opus). No model calls in this ticket except a 30-page smoke test.

Goal: Shivam wants spare hy4 quota spent on investor presentations of the Telegram-list companies outside the 91
built stores (after the KPI dictionary grows). The deck-observation reader (`reality_engine/v2/observations.py`,
merged T-230) needs a store per company. Build the minimal store: company, doc, doc_page, routes.csv - decks only.

Evidence: (Wolf's scout, real)
- Company list: `tasks/handoff/T-232_companies.csv` (560 ISINs outside measure10's 91; 403 have >=1 deck since
  2024-04-01; ~3,510 decks, ~110k pages; ~54 are "Intimation" letters, not decks).
- Deck index: `reality_engine/data/deck_figures.db` table `deck_sources` (local_path under D:/RealityEngine/raw/decks/
  ...; files are on Drive only, manifest `D:/RealityEngine/drive_index/raw_to_drive.db`, fetched through
  `raw_store.RawStore.exists/local` raw_store.py:277/370 and `config.resolve_stored_path` config.py:50).
  deck_sources stops at 25 Oct 2026 (273 later "Investor Presentation" BSE filings for 258 of these are not in it:
  report them, do not fetch in this ticket).
- Store build: `reality_engine/scripts/tg_measure_build.py` `build_company` :259 runs pilot3.make_profile,
  pilot3.docs_collect (dates decks via `_load_decks_ar` docs_collect.py:269; writes doc + doc_page from the text
  layer), `pilot3.build --part` with 13 hard-coded PARTS (:48; registry -> company+doc, pages -> doc_page,
  build.py:203-209) and `v2.page_route --store ... --out routes.csv`. Medians on the 91: docs_collect 23 s, registry
  2 s, pages 2 s, routing 60 s.
- What observations.py reads: doc(doc_key, symbol, doc_type, known_at, source_key, pages), doc_page(doc_key, page,
  text), company(symbol, name), routes.csv beside the store (`pages_from_store` observations.py:1835, `page_meta`
  :1579, `page_text_of` :1591, `company_index` :779); images via RawStore.local(source_key).

Steps:
1. Add `--parts` (default = today's PARTS, unchanged behaviour), a `--doc-types` filter (docs_collect collects only
   those types, so only decks are fetched from Drive), `--universe <csv>` and `--root <dir>`, so the new stores live
   under `D:/RealityEngine/tg_build/decks403/dNNN/` (never touch measure10).
2. Deck profile: parts registry + pages; routing with --doc-types deck. Skip "Intimation" letters.
3. The reader needs page images later, so keep fetched deck PDFs only in the RawStore cache, record bytes held, and
   report total disk use. D: is an HDD with a BSOD history under heavy writes: at most 2 companies in parallel.
4. Pilot 10 companies (seed 5 from the 403): verify each store opens, has doc/doc_page/company and routes.csv; run
   `python -m reality_engine.v2.observations --stores <3 pilot stores> --doc-types deck --limit 30 --out
   .tmp/t232/obs_pilot.db` as a smoke test (hy4, 30 pages only). Report, then STOP and wait for Wolf's followup.
5. On go: all 403, resumable (skip complete stores); log per company seconds, decks, pages, route counts, failures.
6. Tests for the new flags (synthetic, no network) in `reality_engine/tests/test_tg_measure_build.py` (create if
   absent). Doc: the existing tg build doc (find it under docs/) - new section.

Files: `reality_engine/scripts/tg_measure_build.py`, `reality_engine/pilot3/docs_collect.py` (doc-type filter only),
the test file, the doc. No other file; do not edit tasks/STATE.md.

Accept: tests pass; typecheck clean on changed files; pilot report; default behaviour of tg_measure_build unchanged.

Stop if: a pilot store lacks doc_page for >20% of deck pages; Drive fetch fails for >10% of decks; free space on D:
drops under 50 GB.

Budget: about 2 hours coding; the 403-company build is a long resumable run.
