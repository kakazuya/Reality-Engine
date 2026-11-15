# T-214 step 3: build 10 Telegram-queue companies with scripts only, and measure each

Ticket: T-214
Goal: build one pilot3 store per company for the first 10 companies of the Telegram queue, script layers only
(no model call, no embedding, no OCR), and record what each build costs. The numbers size the 93-company batch.

Files:
- Universe (10 symbols, PRIVATE: never copy names or the list into the repo, commits or docs; refer to "company 1..10"):
  `D:/RealityEngine/tg_build/measure10/universe10.csv`.
- Raw: fetched by Wolf on 15 Nov with `fetch_pilot60_history --fetch --window-start 2024-04-01`; PDFs under
  `D:/RealityEngine/raw/pilot60_history/<SYMBOL>/<bucket>/`, per-run manifest
  `D:/RealityEngine/tg_build/measure10/manifest.csv` (2,266 filings listed before skips; read only `status='ok'`).
- Recipe: `docs/DEVELOPER_GUIDE.md`, bullet "T-208 unseen stores: KEI, MEDANTA, PVRINOX" (same commands, no code change):
  `python -m reality_engine.pilot3.make_profile <SYM> --name <n> --root D:\RealityEngine\tg_build\measure10\<n> --window-start 2024-04-01 --compute-start 2019-01-01 --out <n>_profile.json`,
  then `docs_collect --profile <json>` (writes `pages.db`), then `build --profile <json> --out <n>.db --part <part>` for
  `registry pages transcripts kpi guidance stores comparatives preferred ratios segments notes checks events`, one log `b_<part>.log` per part.
- Page routes: `reality_engine/v2/page_route.py` (`no_figures` / `text_ok` / `needs_ocr` / `table_or_chart`).

Store names: use `--name c01` ... `c10` in queue order (rows of universe10.csv), so stores are `D:/RealityEngine/tg_build/measure10/cNN/cNN.db`; no symbol in any repo file.
Fetch result (15 Nov 18:54): 1,834 ok files, 4.36 GB: material_filing 1,490, quarterly_results 136, investor_presentation 95, concall_transcript 45, annual_report 33, press release 14; 31 PDFs guessed scanned.

Steps:
1. Write `reality_engine/scripts/tg_measure_build.py`: for one symbol run the recipe part by part as subprocesses
   (hidden: CREATE_NO_WINDOW, no shell), and record per part: wall seconds, return code, peak RSS of the child tree
   (psutil, sample every 1 s). One company at a time; never two builds in parallel.
2. Per company also record: ok raw files and bytes, docs, pages, pages by route, table_or_chart pages whose document
   is a results filing with `fin_quarter_xbrl` rows for that quarter ("already covered by XBRL"), store size on disk,
   row counts of fin_quarter_xbrl, fin_quarter_printed, kpi_series, guidance, transcript_statement, shp_category,
   price_delivery, and every part with rc != 0 with the last 5 log lines.
3. Run it for company 1 first. If it works, run the other nine in queue order.
4. Write `D:/RealityEngine/tg_build/measure10/pilot10_measure.csv` (one row per company) and `parts.csv` (company x part).
5. Docs: a DEVELOPER_GUIDE bullet (command, columns, totals and medians WITHOUT company names), STATE line.

Accept: `python -m pytest -q reality_engine/tests/test_tg_measure_build.py` (peak-RSS sampler + CSV row on a fake part) passes; `pilot10_measure.csv` has 10 rows; final answer gives median and max of wall time, peak RAM, store MB, pages, table_or_chart share, and lists every failed part.
Evidence: s10 stores built this way had 284-425 docs, 3,500-3,800 pages, 25-80 MB; these 10 are small caps with ~140-420 filings each since April 2024. Known trap: `schema.create` DROPS tables; per-company builds use separate `--out` files so this is safe, but never point two companies at one db. Sector labels from the master are useless here ("General Diversified"): record the sector key make_profile picks, do not fix it.
Pitfalls: MSI RAM is short (about 5 GB free): stop a part if the child tree passes 4 GB and record it as `ram_stop`. Raw PDFs are local for this run; do not call rclone. Do not write anywhere on D: outside `D:/RealityEngine/tg_build/measure10/`. No code change under `reality_engine/pilot3/` or `reality_engine/v2/`: a part that fails is a finding, not something to fix in this ticket.
Stop if: company 1 fails in `docs_collect` or `registry` (report the log); or any single part runs over 40 minutes.
Budget: 4 hours, DeepSeek max effort.
