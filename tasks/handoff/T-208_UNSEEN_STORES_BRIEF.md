# T-208: three unseen test company stores (KEI, MEDANTA, PVRINOX)

Ticket: T-208

Goal: Shivam 13 Nov: the answer-path verdict needs at least three companies nobody has tuned on. Build a pilot3 store
for each of KEI (INE878B01027, capital goods), MEDANTA (INE474Q01031, healthcare services) and PVRINOX (INE191H01014,
media) from the s10 raw already fetched (T-168), exactly the way the Blue Star store was built, with no code change
for any one company. These are measurement sets: build them, do not answer or read any question about them.

Evidence (checked by Claude 13 Nov):
- Blue Star recipe: `D:/RealityEngine/bluestar/build.sh` runs `python -m reality_engine.pilot3.build --profile
  <profile.json> --out <db> --part <part>` for parts registry pages transcripts kpi guidance stores comparatives
  preferred ratios segments notes checks events, logging `b_<part>.log`. Profile format:
  `D:/RealityEngine/bluestar/bluestar_profile.json` (name, pages_db, raw_root, manifest, out, window_start
  2024-04-01, compute_start 2019-01-01, companies[symbol, name, bse_code, isins, sector, lender]).
  How Blue Star's raw/, manifest.csv and pages.db were produced: `D:/RealityEngine/bluestar/fetch.sh`, `fetch2.sh`,
  `b_fetch.log`, `b_pages.log`, `b_docs_collect.log`, and `docs/DEVELOPER_GUIDE.md` (T-199 block near line 774).
- s10 fetch (10 Nov): `D:/RealityEngine/s10/fetch.log` (2,719 files ok, 29 no_file, manifest rows 56,386; a scan
  pass flagged ~51 likely scanned PDFs); `D:/RealityEngine/s10/universe_s10.csv`. Find the script that wrote that log
  (grep the log's phrases in `reality_engine/`) and where it put the files and manifest; raw files may live only on
  Drive (`raw_store`): fetch through it, never re-download from the exchange what is already held.
- Sector keys: use the sector dictionary the build already has; if none fits a company, use the closest and name it.

Steps:
1. Find the s10 raw and manifest for the three symbols; count documents per family (results, transcripts, decks,
   annual reports, announcements, SHP, ratings) per quarter since 2024-04-01. Write `D:/RealityEngine/s10/<sym>/
   coverage_before.csv`.
2. Per company, under `D:/RealityEngine/s10/<sym>/`: profile json, pages.db (text layer only; pages with no or a
   jumbled text layer are LISTED in `ocr_needed.csv`, not OCR'd: OCR runs on the HP by a separate job), then the
   build parts in the Blue Star order into `<sym>.db`. Same part list; a failing part stops that company, logs the
   tail, and you continue with the next company.
3. Do NOT run the embedding step (paid DeepInfra needs Shivam's OK) and do not run any model-based reader or Beam
   step; script parts only. Name in your answer which parts are model-based and were skipped.
4. Coverage after: per company, per table (doc, doc_page, fin_quarter_xbrl, fin_quarter_printed, kpi_series,
   guidance, transcript_statement, shp_category, shp_pledge, insider_trade, price_delivery) row counts and latest
   known_at; compare with bluestar.db's counts. `D:/RealityEngine/s10/coverage_after.csv`.
5. Registry: write the three stores into a NEW registry file `D:/RealityEngine/s10/stores_s10.json` in the format
   `python -m reality_engine.scripts.store_registry` uses; do not edit the live registry (Claude does after review).
6. Docs: `docs/DEVELOPER_GUIDE.md` short block "T-208 unseen stores" (commands, counts, skipped parts) and one line
   per step in `PROGRESS_NOTES.md`.

Files: write only under `D:/RealityEngine/s10/{kei,medanta,pvrinox}/`, `D:/RealityEngine/s10/*.csv|json` named above,
`docs/DEVELOPER_GUIDE.md`, `PROGRESS_NOTES.md`. No code change; if the build needs one, stop and describe it.
Accept: python -c "import pathlib,sys;sys.exit(0 if all(pathlib.Path(f'D:/RealityEngine/s10/{s}/{s}.db').exists() for s in ('kei','medanta','pvrinox')) else 1)"
Pitfalls: never trust the exchange's category or headline for doc type (the build's own type dictionary decides);
check stored dates against the filing record on the first rows (doc_date is often crawl date); known_at must be the
exchange dissemination time; never touch bluestar/aurobindo stores; no pop-up windows (CREATE_NO_WINDOW).
Stop if: the s10 raw for a company is missing a whole family (say which, continue with the others); a build part
needs a code change; RAM over 90% (MSI is short of RAM until 15 Nov: run one company at a time); 4 hours.
Budget: 4 hours, 300 tool calls.
