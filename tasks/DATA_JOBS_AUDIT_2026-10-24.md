
# DATA JOBS AUDIT — 2026-10-24 (Phase 0, read-only)

**Scope:** every recurring data job in `Info_Diffusion_Model` — scripts, `.cmd` launchers, `reality_engine/pipeline/`, `reality_engine/cli.py`, Windows scheduled tasks, and the output-table freshness of each.
**Method:** source + launcher read, log tail, `max(date)`/`max(fetched_at)`/`max(created_at)` per output table via the reality-data MCP `sql` tool (read-only). Nothing was written, fetched or ingested.
**Audit time:** 2026-10-24 05:30 IST (Saturday). Last trading session: **Fri 2026-10-23**.

## 0. What could and could not be verified

| Item | Status |
|---|---|
| Scripts, `.cmd`, pipeline, cli, logs, docs | **Verified** (read) |
| DB freshness, per table | **Verified** (MCP `sql`, read-only) |
| Windows Task Scheduler state (names, enabled, LastRunTime, LastResult) | **UNVERIFIED — blocked.** `schtasks /query` and the `ScheduledTasks` CIM module are both inaccessible under this read-only sandbox (`Access to a CIM resource was not available`); registry TaskCache also unreadable. Escalation had no approval channel. Task names below are from repo code/`.cmd` headers; **state from `tasks/STATE.md` only.** |
| Live process list (is anything running *now*) | **UNVERIFIED** — no such job is evidenced by any log after 2026-10-21 |
| `reality_engine/data/raw_market/` | **Does not exist on this machine** (verified) — so no raw-file replay is possible locally |

## 1. Machine state (verified except where marked)

- `tasks/STATE.md:31`: *"all RealityEngine-* scheduled tasks disabled at Shivam's request, 01:30 IST. **Re-enable only on his word.** PC reported shut down until approximately 26/27-Nov. Laptop is the main workstation."* → every scheduled job below is presumed **disabled (unverified)**.
- The 2026-10-21 restore replaced `reality_engine/data/*.db` with the **19-Oct 16:50 PC copies**; only PIB / policy / concall tables were merged forward (`STATE.md:33-37`). **Anything ingested on the laptop after 19-Oct 16:50 and not merged is missing from the live DB** (it survives only inside `truth_2026-10-19.duckdb`). This alone explains several "regressions" below.
- `reality_engine/data/raw_market/` **missing**; `data/bhavcopy/`, `data/pdfs/`, `data/macro_pdfs/` **empty (0 files)**. `data/snapshots/` holds **one** file: `truth_2026-10-19.duckdb`. Live DB mtimes: `equity_intelligence.db` 2026-10-21 14:38; `concall_facts.db` 2026-10-20 23:32; others 2026-10-19 16:2x.
- Startup folder: no watchdog entry (only OneNote). `run_resource_watchdog` is not auto-started here.
- No `plugins/dsh-worker/jobs.yaml` exists yet (Phase 2 deliverable).
- `reality_engine/agent/routines.json` = `{"routines": []}` → the 5-minute `RealityEngine-Routines` tick dispatches **nothing**.

## 2. Answer to the question, in one paragraph

Most of the *big* backfills did run and did finish — prices, corporate actions, deals, FII/DII, shareholding, NSE industry, results XBRL, policy register, 2026 concalls — and their data is real and usable **up to 2026-10-16 / 2026-10-19**. What actually stopped is (a) the **nightly EOD chain**, which is the only thing that keeps 20+ upstream feeds current, last fully successful **2026-10-19**, and which since **2026-10-20** silently fetches *nothing* because the exchange file looks "missing" rather than erroring; (b) the **normalized price table the whole backtest harness reads** (`daily_price_delivery`), which starts only 2021-10-27 and froze on **2026-09-24**; (c) a **9-month PIB English hole** (2025-12-20 → 2026-09-24); and (d) the **document/quota-bound jobs** (deck figures, AR ingest, weekly SEBI, news). Two tables were **never populated at all** (`insider_trades`, `financially_free_breadth`), two are **dead by upstream change** (`mkt_nse_sme_daily`, `mkt_bse_insider`), and the **DB backup job is broken** (PermissionError on its own log, uploaded set incomplete).

## 3. Job inventory

Legend — **Task**: scheduled-task name (`disabled` = per STATE.md 2026-10-21 01:30). **Last success**: date + source of evidence. **Latest data**: `max()` in the output table. **Verdict**: fresh / stale / never ran / broken / unknown.

### 3.1 Market data feed chain (the priority chain)

| # | Job | Entry point (exact) | Writes | Cadence | Task | Last evidence of success | Latest data | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | Exchange daily files (NSE full/CM-ISIN/indices/SME, BSE bhav+deliv, participant OI+vol, FII stats) | `python -m reality_engine.scripts.fetch_market_raw --sources nse_full,nse_cm_isin,nse_index,bse_bhav,bse_deliv,nse_part_oi,nse_part_vol,nse_fii_stats --start <D-10> --end <D>` | `data/raw_market/<source>/` → then loaded (row 6) | daily EOD (step 1 of EOD) | inside `RealityEngine-EODMarket` (disabled) | `eod_market.log` 2026-10-19 19:35 `exchange files rc=0`; `mkt_load_log` last load **2026-10-19T01:45** | `mkt_nse_full_daily` **2026-10-16** | **stale** (5 sessions) |
| 2 | NSE API raw (bulk/block/short, PIT feed+XML, SAST, corp actions) | `python -m reality_engine.scripts.fetch_nse_api_raw --datasets nse_bulk,nse_block,nse_short,nse_pit_gg,nse_pit_gg_sme,nse_pit_gg_xml,nse_sast,nse_corpact,nse_corpact_sme --start <D-10> --end <D>` | `data/raw_market/nse_*` | daily EOD (step 2) | same | `eod_market.log` 2026-10-19 19:35 `nse api rc=0` | `mkt_nse_deals`/`mkt_nse_sast`/`mkt_nse_pit_filings` 2026-10-16; `mkt_nse_short` 2026-10-15 | **stale** |
| 3 | BSE API raw (bulk/block/insider/index/corp actions) | `python -m reality_engine.scripts.fetch_bse_api_raw --datasets bse_bulk,bse_block,bse_insider,bse_index,bse_corpact --start <D-10> --end <D>` | `data/raw_market/bse_*` | daily EOD (step 3) | same | `eod_market.log` 2026-10-19 19:39 `bse api rc=0` | `mkt_bse_deals` 2026-10-16; `mkt_bse_insider` **2022-06** (upstream) | **stale** |
| 4 | NSDL FPI daily | `python -m reality_engine.scripts.fetch_nsdl_raw --datasets nsdl_fpi_daily --start <D-10> --end <D>` | `data/raw_market/nsdl_fpi_daily/` | daily EOD (step 4) | same | 2026-10-19 19:39 `nsdl fpi rc=0` | `mkt_nsdl_fpi_daily` 2026-10-16 | **stale** |
| 5 | FII/DII cash (Moneycontrol protobuf) | `python -m reality_engine.scripts.fetch_fiidii_moneycontrol --start <D-10> --end <D>` | `data/raw_market/mc_fiidii/<year>.pb` | daily EOD (step 4) | same | 2026-10-19 19:40 `fii/dii cash rc=0` | `mkt_fii_dii_cash` 2026-10-16 | **stale** |
| 6 | Loader (raw → DB) | `python -m reality_engine.scripts.load_market_raw --sources nse_full,nse_index,bse_bhav,bse_deliv,nse_part_oi,nse_part_vol,nse_fii_stats,nse_bulk,nse_block,nse_short,nse_pit_gg,nse_pit_gg_sme,nse_pit_gg_xml,nse_sast,nse_corpact,bse_bulk,bse_block,bse_insider,bse_index,nsdl_fpi_daily,mc_fiidii` | `mkt_*` tables + `mkt_load_log` | daily EOD (step 5) | same | 2026-10-19 19:40 `load rc=0 (23s)` | as rows 1–5 | **stale** |
| 7 | Security master / symbol-ISIN history | `python -m reality_engine.scripts.build_security_master` | `security_master`, `symbol_isin_history` | nightly (EOD step 7) | same | 2026-10-19 19:46 `security master rc=0 (120s)` | `last_seen_nse` 2026-10-16; 8,434 rows | **stale** |
| 8 | NSE circuit hits + price bands / GSM-ASM | `python -m reality_engine.scripts.fetch_nse_pr --start 2019-01-01` (single-shot backfill) | `circuit_hits`, `price_bands`, `nse_pr_days` | once (2019→) + last-10-days nightly (EOD step 13) | inside EOD; also `boot_recover` writer | `nse_pr.log`: `done (1927, 1927, 1679, '2019-01-01', '2026-10-16')` 2026-10-19 17:06 — **482,029 circuit / 4,040,673 band rows** | live: 243,049 rows to **2026-09-22**; snapshot: 482,308 rows to **2026-10-19** | **broken (rolled back)** |
| 9 | NSE industry classification | `python -m reality_engine.scripts.fetch_nse_industry` | `company_industry` | one-shot + monthly | `boot_recover` writer | `nse_industry.log` 2026-10-19 17:03 `done (3178, 3155, 195)` | snapshot of 2026-10-19 | **fresh** (5 d) |
| 10 | Shareholding pattern + pledge | `run_shareholding.cmd` → `--index --start 2021-01`, `--symbols`, `--xbrl`, `--parse` | `shp_index`, `shp_facts`, `shp_parsed`, view `shareholding` | quarterly + backfill | `boot_recover` writer | `shareholding.log` 2026-10-19 23:47 `parsed: [('no_facts',195),('ok',50329)]` of 50,484 | `shp_index` 2021→2026, `broadcast_at` **2026-10-19** | **complete / fresh** |
| 11 | ETF prices + AMFI NAV + iNAV | `python -m reality_engine.scripts.fetch_etf_nav` (EOD step 11; `etf_nav_backfill.log` for full history) | `etf_px`, `etf_master`, `fund_nav`, `etf_inav`, view `etf_premium` | daily EOD | inside EOD | `eod_market.log` 2026-10-19 19:49 `etf nav rc=0`; `etf_nav_backfill.log` 2026-10-19 05:15 (2019→) | `etf_px` 2026-10-16, `fund_nav` 2026-10-18, `etf_inav` 2026-10-16 | **stale** (5 d) |
| 12 | Total-return indices (benchmark rule) | `python -m reality_engine.scripts.fetch_index_tri --start <D-10> --end <D>` | `index_tri` | daily EOD | inside EOD | 2026-10-19 19:48 `index tri rc=0` | 2026-10-16 (19,330 rows, 2019→) | **stale** |
| 13 | Board-meeting calendar | `python -m reality_engine.scripts.fetch_board_meetings --ahead 90` | `board_meetings` | daily EOD | inside EOD | 2026-10-19 19:49 `board meetings rc=0`; `fetched_at` 2026-10-19T05:42 | `meeting_date` **2026-11-14** (forward), 120,600 rows | **fresh** |
| 14 | BSE announcements, market-wide | `python -m reality_engine.scripts.fetch_bse_announcements_daily --start <D-10> --end <D>` | `analysis/bse_announcements.db` table `ann` (mirrored to `reality_engine/data/bse_announcements.db`) | daily EOD (step 6) | inside EOD | 2026-10-19 19:43 `bse announcements rc=0 (185s)` | `ann.DT_TM` **2026-10-19**, 1,947,087 rows (2019-12-31→) | **stale** (5 d) |
| 15 | New transcripts/decks discovery from BSE feed | `python -m reality_engine.scripts.discover_bse_feed_docs --since <D-10>` | `corporate_documents` | daily EOD | inside EOD | 2026-10-19 19:44 `new transcripts/decks rc=0 (67s)` | `corporate_documents.created_at` 2026-10-18 | **stale** |
| 16 | BSE annual-report filing dates (PIT) | `python -m reality_engine.scripts.fetch_bse_annual_report_dates fetch` → `apply` → `report` | `bse_annual_reports` (+ `corporate_documents.publication_date`) | once | none | `fetch_bse_annual_report_dates.log` 2026-10-10 19:56 | `dt_tm` 2026-10-10; 25,462 ARs dated (`STATE.md:994`) | **stale / one-shot done** |
| 17 | Commodity series | `load_market_raw` sources `commodity_*` (fetch via `fetch_market_raw`) | `mkt_commodity_daily`, `mkt_commodity_monthly` | daily | none (inside EOD only partially) | no dedicated log | daily **2026-10-06**, monthly **2025-12** | **stale / partly never ran** |
| 18 | NSE SME bhavcopy (separate file) | `fetch_market_raw --sources nse_sme` | `mkt_nse_sme_daily` | daily | inside EOD | `mkt_load_log` `nse_sme` last file `sme311224.csv` (2026-10-06 run) | **2025-10-10** | **dead (upstream URL change)** — SME prices continue in `mkt_nse_full_daily` (SM 12,076 / ST 2,801 rows to 2026-10-16 ✓) |
| 19 | Index OHLC breadth (4 universe legs) | `python -m reality_engine.scripts.backfill_index_ohlc` | `nse_index_breadth` | daily | none | no log | **2026-09-24** | **stale (abandoned)** |
| 20 | Market breadth (financially_free) | `FinanciallyFreeClient` via `cli run-phase1` only | `financially_free_breadth` | daily | none | none | **empty (0 rows)** | **never ran** |
| 21 | Index membership | `python -m reality_engine.scripts.load_index_membership` | `index_membership` | per rebalance | none | `as_of` 2026-09-30 | 300 rows / 3 indices, **single static snapshot** | **stale / not PIT** |
| 22 | Normalized price+delivery table (technical engine / all backtests) | `python reality_engine/cli.py backfill --days N` → `pipeline/backfill.py`; also `pipeline/nightly_alpha.py`, `pipeline/catchup_scheduler.py` | `daily_price_delivery` | daily | **no `.cmd`, no task, `routines.json` empty** | none in any surviving log | **2021-10-27 → 2026-09-24** (3,795,033 rows) | **stopped + incomplete history** |
| 23 | PIT insider facts (normalized) | `cli run-phase1` → `nse_client.fetch_insider_trades` → `repository.upsert_insider_trades` | `insider_trades` | daily | none | none | **empty (0 rows)** | **never ran** |
| 24 | Legacy NSE PIT monthly feed | `fetch_nse_api_raw --datasets nse_pit` | `mkt_nse_insider` | monthly | none | `mkt_load_log.nse_pit` last file `2026-05` | **2026-05-02** | **stopped** (replaced by `nse_pit_gg`, current to 2026-10-16) |
| 25 | Legacy NSE results XBRL feed | `run_results_xbrl_fetch.cmd` → `fetch_nse_api_raw --datasets nse_results_xbrl` | `results_xbrl.db` | one-shot | none | `fetch_nse_results_xbrl.log` 2026-10-10 17:05 | `filings.period_end` **2026-09-30** (via integrated filing path, row 26) | **superseded** |
| 26 | Integrated results (Mar-2025 →) XBRL | `run_integrated_results.cmd` → `fetch_nse_api_raw --datasets nse_integrated,nse_integrated_xbrl` then `parse_nse_results_xbrl` | `results_xbrl.db` (`filings`, `facts`, view `quarterly`) + `filings_isin` | daily EOD-ish | inside EOD (step 9 `resolve_results_isin` only) | `integrated_results.log` 2026-10-19 04:56 `done`; 30,197 files, 106,286 ok | `period_end` 2026-09-30, 106,613 filings, 13.9M facts | **fresh / complete** |

### 3.2 Document & knowledge corpus

| # | Job | Entry point | Writes | Cadence | Task | Last evidence | Latest data | Verdict |
|---|---|---|---|---|---|---|---|---|
| 27 | PIB English (Delhi HQ) daily + backfill | `run_pib_backfill.cmd` → `python -m reality_engine.scripts.pib_feed --start 2021-01-01` (EOD: last 3 days) | `pib_releases`, `pib_days`, `raw_documents(PIB_Press_Release)`, chunks+FTS | daily + 2021→ backfill | `boot_recover` writer "pib_backfill"; EOD step 8 | `pib_releases.fetched_at` **2026-10-20T23:50**; `pib_feed_a2_window.log` 2026-10-19 20:08 | `release_date` **2026-10-20**; 2021–2025 complete, **but only 26 days in 2026** | **stale + 9-month GAP** |
| 28 | PIB regional/multilingual (+ translation match) | `run_pib_regional.cmd` → `python -m reality_engine.scripts.pib_regional [--start --end]`, `--match title/body` | `pib_ml_releases`, `pib_ml_days`, `pib_ml_langs`, `pib_ml_match` | sample only | `boot_recover` "pib_regional_sample" (2026-09-26..10-05) | `pib_regional.log` 2026-10-19 17:36 (2026-09-26 → 10-03 done); `pib_regional_match_*.log` 2026-10-19 | `release_date` **2026-10-15**; 8,816 releases, 14,416 match rows | **partial — never backfilled** |
| 29 | PIB legacy ingest | `python -m reality_engine.scripts.run_pib_ingest --limit N` | `raw_documents` | one-shot | **none — "was never scheduled"** (`pib_feed.py` docstring) | `pib_ingest.log` 2026-09-21 18:19 | 2 releases | **superseded / never ran** |
| 30 | Policy register over macro docs | `run_policy_register.cmd` → `python -m reality_engine.scripts.policy_register --source doc --doc-types "Union_Budget,Union Budget%,Economic_Survey,RBI%,State_Budget%,PIB_Circular" --workers 24` | `policy_events`, `policy_docs` | once (then `--source pib`) | `boot_recover` writer | `policy_register_docs.log` 2026-10-19 19:33 (last doc batch, 506 events) | `policy_docs` **3,054 / 3,054 ok**; `policy_events` 21,552 rows, `published_at` **2026-10-16** | **doc pass COMPLETE; `--source pib` pass never started** |
| 31 | Macro document fetch (Budget/Survey/RBI/state) | `python -m reality_engine.scripts.fetch_macro_docs --sources union,survey,rbi,states` | `data/macro_pdfs/`, `raw_documents` | annual | none | `fetch_macro_all.log` 2026-10-17 23:41 | `Union_Budget` 2026-02-01, `RBI_Monetary_Policy` 2026-10-07, 3,520 docs total | **stale (annual cadence, ok)** |
| 32 | AR download (PDFs) | `run_ar_download_d.cmd` (`run_annual_report_ingest --download-only --since 2019-04-01 --active-since 2025-10-01`), `run_filing_download.cmd [ar\|concall\|both]` | `corporate_documents.local_file_path`, files in `REALITY_ENGINE_PDFS_DIR` (D:) | one-shot backfill | none | `annual_report_ingest.log` 2026-10-19 05:25 | **`data/pdfs/` is empty on this machine; `D:\RealityEngine\pdfs` not present** | **broken here (corpus absent)** |
| 33 | AR fact extraction (LLM readers) | `run_ar_ingest.cmd` / `run_ar_google.cmd` / `run_ar_gflash31.cmd` / `run_ar_ggemma26.cmd` / `run_ar_zen.cmd` → `python -m reality_engine.scripts.ingest_annual_reports [--route ...]` | `ar_facts.db` (`ar_docs`, `ar_facts`, `ar_pieces`, `ar_claims`, FTS) | continuous | **`RealityEngine-AnnualDrain` DISABLED 2026-10-11 01:30** (`STATE.md:958`); `run_annual_drain.cmd` = hourly watchdog | `ingest_annual_reports*.log` last 2026-10-18 03:55 (`zen`); `annual_drain_watchdog.log` last 2026-10-11 01:25 | `ar_docs` 33,705 (filed_at → 2026-09-07), `ar_facts` 32.4M | **stopped (quota + task disabled)** |
| 34 | AR chunking into search layer | `run_ingestion_queue.py --only annual_n200 --batch 10` (via `run_annual_drain.cmd`) | `document_chunks`, `intelligence_fts` | hourly | AnnualDrain (disabled) | `ingestion_queue.log` 2026-10-10 20:40 | `raw_documents(ANNUAL_REPORT)` **3,520** docs, last 2026-09-25 | **stopped / far from complete** |
| 35 | Deck discovery (investor presentations) | `python -m reality_engine.scripts.fetch_decks [bse\|nse] --since 2021-01-01` | `data/decks/{bse,nse}`, `deck_figures.db:deck_sources` | one-shot | none (watchdog-managed while running) | `fetch_decks.log` 2026-10-09 04:33 | `deck_sources.known_at` **2026-09-29**, 26,391 rows | **stale (2020 decks not fetched)** |
| 36 | Deck figure extraction (vision) | `run_deck_extract.cmd` → `python -m reality_engine.scripts.extract_deck_figures`; `run_deck_redo_deferred.cmd` | `deck_figures.db: pages, outputs, facts, chart_trends, spend` | continuous | none (watchdog) | `extract_deck_figures.log` 2026-10-14 12:01; `passes.log` same | `pages` 815,837; `facts` 13.57M | **stopped** |
| 37 | Concall extraction (2026 set) | `run_concall_deepseek.cmd` → `python -m reality_engine.scripts.concall_deepseek --workers 25 --week-cap 1000` | `concall_facts.db` (`cc_docs`, `cc_items`, FTS) | continuous | none | `concall_deepseek.log` 2026-10-19 03:35 `RUN_COMPLETE` (1,056 ok) | `cc_docs.filed_at` **2026-10-14**, 9,294 docs / 644,957 items | **complete for scope, stale** |
| 38 | Weekly SEBI offer documents (DRHP) | `run_weekly_sebi_ingest.cmd` → `python -m reality_engine.scripts.weekly_sebi_ingest --since 2021 --workers 4` | `raw_documents(OFFER_DOCUMENT)`, chunks, substrate | weekly | `RealityEngine_WeeklySEBIIngest` (state unverified) | `offer_backfill/weekly_task.log` 2026-10-18 03:04 | `OFFER_DOCUMENT` **909** docs, last 2026-09-17 | **stale** |
| 39 | Telegram posts / PEAD / orders | `python reality_engine/scripts/tg_backfill.py [--topics ...]`, `cli listen-telegram`, `scripts/tg_pead_signals.py`, `tg_orders.py` | `telegram_posts`, `tg_pead_signals`, `tg_orders`, `tg_company_mentions` | live listener + backfill | none | `telegram_posts.created_at` 2026-10-18 17:37 | posts **2026-10-18**, PEAD signals **2026-10-17** (731) | **stale** (session is per-machine; laptop has its own) |
| 40 | Video / YouTube ingestion | `python reality_engine/scripts/ingest_video_batch.py --all` | `raw_documents(YouTube_*)`, chunks w/ timestamps | one-shot | none | none since | `YouTube_DailyBytes` 65 docs, last 2026-09-29 | **stale / ad hoc** |
| 41 | News loop (RSS + infographic OCR + prune) | `run_news_loop.cmd` → `python -m reality_engine.pipeline.news_loop --run` | `raw_documents(news_*)`, `intelligence_fts`, `news_visual_artifacts` | daily | `RealityEngine-NewsLoop` (created by `--install`; **no log ever found**) | no `news_loop` log exists in live or archived logs | `news_*` rows last **2026-09-26** | **stale / likely never scheduled** |
| 42 | Inbox ingestion (local PDFs) | `python reality_engine/cli.py process-inbox` | `raw_documents`, chunks, `inbox_ingestion_manifest` | manual | none | none | `data/inbox/` empty | **never ran (nothing to ingest)** |

### 3.3 Derived / promotion / validation

| # | Job | Entry point | Writes | Cadence | Task | Last evidence | Latest data | Verdict |
|---|---|---|---|---|---|---|---|---|
| 43 | Truth snapshot (research layer) | `python -m reality_engine.scripts.build_truth_snapshot` | `data/snapshots/truth_<date>.duckdb` | nightly (EOD step 14) | inside EOD | `truth_snapshot_build.log` 2026-10-19 05:21; EOD 2026-10-19 21:03 rc=0 | **one file: 2026-10-19** (63 tables, `px_daily` 7.26M rows 2019→2026-10-19) | **stale (5 d)** |
| 44 | Nightly chain (master sync → backfill → fundamentals → screens → EOD correction) | `python -m reality_engine.pipeline.nightly_runner` / `cli nightly` / `pipeline/catchup_scheduler.py run_catchup` | `daily_price_delivery`, screens, `eod_scrip_calls`, `move_attribution` | twice daily 16:00/23:00 | **described in docstring, but no `.cmd` and no task found; `routines.json` empty** | none | — | **never scheduled** |
| 45 | Peer / substrate promotion runs | `run_peer_graph.py`, `run_entity_graph.py`, `run_business_peer_graph.py`, `run_substrate_hygiene.py`, seeds (`seed-*`) | `company_peer_*`, `business_model_*`, `substrate_quarantine`, `model_explainer_rankings` | on demand | none | `STATE.md` 2026-10-19 | not re-run since | **manual / unknown** |
| 46 | Data-quality gates | `cli audit-data` → `pipeline/data_audit.py`; `python -m reality_engine.scripts.coverage_report`; `scripts/state_check.py`, `state_handcheck.py` | report only (stdout) | per release | none | `state_handcheck` results in `STATE.md:281` | — | **run manually, no artifacts kept** |
| 47 | Query-speed check | `python -m reality_engine.scripts.query_speed_check` | `query_speed.jsonl`, `query_speed_report.md` | nightly (EOD step 15) | inside EOD | `eod_market.log` 2026-10-20 21:14 rc=1 "6 OVER LIMIT" | 2026-10-20 | **ran, over limit (advisory)** |

### 3.4 Ops / supervisor jobs

| # | Job | Entry point | Task | Last evidence | Verdict |
|---|---|---|---|---|---|
| 48 | Boot recovery (restart all jobs after power cut) | `pythonw -u -m reality_engine.scripts.boot_recover` | `RealityEngine-BootRecover` (startup + logon, S4U) — **disabled** | `boot_recover.log` 2026-10-20 12:20; `boot_recover_status.json` | **ran on PC; not installed here** (no Startup entry, task unverified) |
| 49 | Resource watchdog | `python -m reality_engine.scripts.resource_watchdog` | Startup folder / `run_hidden.vbs` | `resource_watchdog_report.md` 2026-10-20 23:06; `resource_incidents.jsonl` | **not running here** (no autostart) |
| 50 | DeepSeek heartbeat (hourly) | `run_deepseek_heartbeat.cmd` → `python -m reality_engine.scripts.deepseek_heartbeat` | `RealityEngine-DeepSeekHeartbeat` — **disabled** | `deepseek_heartbeat.log` hourly rc=0 to 2026-10-20 23:04 | **stale / disabled** |
| 51 | DB backup to Drive | `run_db_backup.cmd` → `python -m reality_engine.scripts.backup_dbs_to_drive` | `RealityEngine-DBBackup` (daily 05:00) — **disabled** | `db_backup.log` 2026-10-20 13:17 **`PermissionError: … data\logs\db_backup.log`**; `set 2026-10-19: check found missing/differing parts (rc 1)` | **BROKEN** |
| 52 | Capacity loop (report-only) | `run_capacity_loop.cmd` → `pipeline/capacity_loop` | `RealityEngine-CapacityLoop` (`--install`) | `data/logs/capacity/` (archived) | **unknown — no evidence since Sep** |
| 53 | Continuous loop (30-min agent pass) | `run_continuous_loop.cmd` → `pipeline/continuous_loop --agent` | `RealityEngine-ContinuousLoop` (`--install`) | `data/logs/loop/<date>/` — last 2026-09-26 | **stopped** |
| 54 | Forecast tester | `run_forecast_tester.cmd` → `pipeline/forecast_tester` | `RealityEngine-ForecastTester` (`--install`) | `data/logs/forecast/` (archived) | **unknown — no evidence since Sep** |
| 55 | Routines dispatcher (5-min) | `run_routines.cmd` → `pipeline/routines --tick` | `RealityEngine-Routines` (`--install`) | `reality_engine/agent/routines.json` = `[]` | **installed but empty → does nothing** |
| 56 | Drive upload / archive | `run_pdf_upload.cmd`, `run_archive_to_drive.cmd` | none (rclone) | `pdf_upload.rclone.log` 2026-10-20 17:09 | **stopped** |
| 57 | DB merge / one-off migrations | `merge_lane_db.py`, `merge_placeholder_isins.py`, `rekey_placeholder_isins.py`, `migrate_*`, `restore_*` | various | one-shot | 2026-10-21 restore session | **done, not recurring** |

### 3.5 CLI commands that write data (not covered above)

`sync-master` (`master_sync`) · `fetch-fundamentals` (`fundamentals_client`) · `discover-filings` / `fetch-filings` · `fetch-offer-docs` / `offer-backfill` · `fetch-corporate-actions` / `fetch-corporate-status` · `fetch-macro` / `process-macro` · `fetch-announcements` / `fetch-deals` / `fetch-news` · `run-phase1` (writes `daily_price_delivery`, `insider_trades`, `nse_index_breadth`) · `run-moe-eod` / `correct-eod` / `correct-event` · `run-distillation` / `distill` · `embed-setup` / `reembed-chunks` · `import-plexity`-family · `seed-*` / `prune` / `run-calibration`.
**All are manual.** None has a `.cmd`, a scheduled task or a `routines.json` entry, and none has log evidence after 2026-10-19. `sync-master`, `fetch-fundamentals`, `fetch-announcements`, `fetch-deals`, `run-phase1` should be treated as **never ran on this machine**.

## 4. The specific findings that matter

1. **Silent EOD stall since 2026-10-20.** `eod_market.log` shows the 2026-10-19 19:35 run finishing every step `rc=0` (data loaded through 2026-10-16). The **2026-10-20** run reports `missing: 1` for **all eight** exchange-file sources (`nse_full`, `nse_cm_isin`, `nse_index`, `bse_bhav`, `bse_deliv`, `nse_part_oi`, `nse_part_vol`, `nse_fii_stats`) — i.e. it never obtained the 2026-10-19 or 2026-10-20 file — then `analysis snapshot rc=1 (database is locked)`. `run_eod_market` treats a missing file as a *skip*, so the run still exits 0. **A whole-chain failure is reported as success.** Root cause **unverified**: publishing delay vs. archive-naming change vs. site block. This is exactly the failure mode `jobs.yaml` success-checks must catch.
2. **The backtest price table is stale and too short.** `daily_price_delivery` — read by `composite_screener`, `validation_harness`, `desk_backtest`, `sip_backtest`, `eod_corrector`, `panic_monitor`, `attention_ranker`, `forecast_tester`, `coverage_report`, `data_audit` — covers **2021-10-27 → 2026-09-24**. FRAMEWORK §5 needs **2021-01-01 → 2025-12-31** plus 2019–20 warm-up. With this table the evidence window **cannot be reached** (missing 2021-01-01…2021-10-26 and everything after 2026-09-24). `px_daily` in the DuckDB snapshot *does* cover 2019→2026-10-19 for 4,300–5,600 entities/year.
3. **PIB English hole: 2025-12-20 → 2026-09-24.** `pib_days` has 365/365/365/366 days for 2021–2024, **353 days in 2025 (last 2025-12-19)**, then jumps to **2026-09-25** and runs to 2026-10-20 (26 days). The backfill stopped at the 2025 year-end and the daily mode resumed only in late September. Counts: 73,798 releases for 2021–2025, **1,331 for all of 2026**.
4. **Restore rollback, not a job failure.** `circuit_hits` (243,049 rows, 2019-01-01→**2026-09-22**) and `price_bands` (1,054,356 rows→2026-09-22) are *smaller and older* than the 2026-10-19 snapshot of the same tables (482,308 rows→**2026-10-19**; `nse_pr.log` final tally 482,029 + 4,040,673). The 2026-10-19 17:06 run **succeeded**; the 2026-10-21 restore replaced `equity_intelligence.db` with the 19-Oct-16:50 copy. **Inference, high confidence** (`STATE.md:37` documents the 16:50 cutoff). Same class of loss should be checked for any other table written after 19-Oct 16:50 — today only `circuit_hits` / `price_bands` show it.
5. **Two tables never populated**: `insider_trades` (0 rows — the normalized PIT path only runs inside `run-phase1`) and `financially_free_breadth` (0 rows). Consumers of `get_recent_insider_trades()` silently receive nothing.
6. **No scheduler at all for the nightly research chain.** `nightly_runner` / `catchup_scheduler` docstrings promise 16:00 & 23:00 IST runs; there is no `.cmd`, no task name in code, and `routines.json` is empty. `run-phase1`, `backtest`, `nightly` have never run automatically.
7. **The DB backup is broken** — `PermissionError` writing its own log file (2026-10-19 16:23), and the uploaded set from 2026-10-19 failed its own verification (`missing/differing parts`).
8. **Dead-by-upstream feeds** (not project failures, must be recorded so nothing waits on them): `mkt_nse_sme_daily` (2025-10-10, URL change; SME prices continue in `mkt_nse_full_daily` as SM/ST), `mkt_bse_insider` (2022-06; BSE publishes header-only after 2022), `mkt_nse_eq_daily` (2021-10-29; superseded by `mkt_nse_full_daily`), `mkt_nse_insider` (2026-05-02; superseded by `mkt_nse_pit_filings`).

## 5. Freshness appendix (verified `max()` values, 2026-10-24)

| Table | max date/ts | rows | Verdict |
|---|---|---|---|
| `mkt_nse_full_daily` | 2026-10-16 (from 2019-06-27) | ~4.48M | 5 sessions behind |
| `mkt_bse_eq_daily` | 2026-10-16 | 7,474,652 | 5 sessions behind |
| `mkt_bse_delivery_daily` | 2026-10-16 | 7,474,563 | 5 sessions behind |
| `daily_price_delivery` | **2026-09-24** (from 2021-10-27) | 3,795,033 | 1 month behind + short history |
| `mkt_nse_sme_daily` | 2025-10-10 | 254,181 | dead (upstream) |
| `mkt_nse_eq_daily` | 2021-10-29 | 1,388,730 | legacy |
| `mkt_nse_deals` / `mkt_bse_deals` | 2026-10-16 | 138,572 / 135,545 | stale 5 d |
| `mkt_fii_dii_cash` | 2026-10-16 (from 2019-01-01) | 1,935 | stale 5 d |
| `mkt_nsdl_fpi_daily` | 2026-10-16 | 33,123 | stale 5 d |
| `mkt_nse_participant` | 2026-10-16 | 19,215 | stale 5 d |
| `mkt_nse_short` | 2026-10-15 | 45,481 | stale 6 d |
| `mkt_nse_sast` | 2026-10-16 12:07 | 37,068 | stale 5 d |
| `mkt_nse_pit_filings` | 2026-10-16 19:10 | 3,862 | stale 5 d |
| `mkt_nse_insider` | 2026-05-02 16:46 | 176,865 | legacy path |
| `mkt_bse_insider` | 2022-06-01 | 153,904 | dead (upstream) |
| `circuit_hits` | **2026-09-22** (snapshot: 2026-10-19) | 243,049 (snapshot 482,308) | rolled back |
| `price_bands` | **2026-09-22** (snapshot: 2026-10-19) | 1,054,356 (snapshot 4,040,673) | rolled back |
| `nse_pr_days` | 2026-09-22 | 783 | rolled back |
| `mkt_nse_index_daily` / `mkt_bse_index_daily` | 2026-10-16 | 205,875 / 143,646 | stale 5 d |
| `index_tri` | 2026-10-16 (from 2019-01-01) | 19,330 | stale 5 d |
| `index_membership` | as_of 2026-09-30 | 300 | static, not PIT |
| `nse_index_breadth` | 2026-09-24 | 5,049 | abandoned |
| `financially_free_breadth` | — | **0** | never ran |
| `etf_px` / `etf_inav` | 2026-10-16 | 313,844 / 6,780 | stale 5 d |
| `fund_nav` | 2026-10-18 | 329,490 | fresh |
| `mkt_commodity_daily` / `_monthly` | 2026-10-06 / 2025-12 | 25,255 / 9,208 | stale |
| `pib_releases` | 2026-10-20 (gap 2025-12-20→2026-09-24) | ~75.1k | stale + gap |
| `pib_ml_releases` | 2026-10-15 | 8,816 | sample only |
| `policy_events` / `policy_docs` | 2026-10-16 / 2026-10-19 | 21,552 / 3,054 ok | doc pass complete |
| `shp_index` | broadcast 2026-10-19 (2021→) | 50,329 ok | fresh |
| `corporate_actions` | fetched 2026-10-18, ex_date 2026-10-16 | ~18.2k | stale 5 d |
| `corporate_documents` | created 2026-10-18, doc_date 2026-10-17 | — | stale 5 d |
| `raw_documents` | published 2026-10-16, created 2026-10-19 11:05 | — | stale 5 d |
| `board_meetings` | fetched 2026-10-19, meeting_date 2026-11-14 | 120,600 | fresh |
| `telegram_posts` | 2026-10-18 | — | stale |
| `results_xbrl.filings` | period_end 2026-09-30 | 106,613 | complete to Q2 FY27 |
| `ar_facts.ar_docs` | filed_at 2026-09-07 | 33,705 | stopped |
| `deck_sources` | known_at 2026-09-29 | 26,391 | stopped |
| `concall_facts.cc_docs` | 2026-10-14 | 9,294 | stopped |
| `truth_2026-10-19.duckdb` | 2026-10-19 (px_daily 2019→10-19) | 7.26M px rows | stale 5 d |
| `ann` (BSE announcements) | DT_TM 2026-10-19 | 1,947,087 | stale 5 d |

## 6. What to run first (FRAMEWORK §1: data before testing)

Ordered so that each step unblocks the next. Nothing below needs the GPU; only rows marked **$** need a paid/quota LLM.

**P0 — unblock the truth layer (do this first, in this order)**

1. **Restore the raw market cache.** `reality_engine/data/raw_market/` does not exist, so `load_market_raw` has nothing to load and every resume ledger (`raw_market/*/_manifest.csv`) is gone. Run `python -m reality_engine.scripts.fetch_market_raw --sources <all> --start 2019-01-01` (≈1,900 files/source; NSE old CM + MTO needed for 2019→2021-10). *No GPU, no paid API, network-heavy, ~1–2 days.*
2. **Find and fix why the daily exchange file stopped arriving after 2026-10-16** before re-running anything — `fetch_market_raw` logs `missing` and returns 0, so a re-run today would "succeed" and load nothing. Verify the current NSE UDiFF / BSE UDiFF file names and that the 2026-10-19..10-23 files actually exist upstream.
3. **Load and extend the `mkt_*` layer to 2026-10-23**: `python -m reality_engine.scripts.load_market_raw --sources <LOAD list>` then `build_security_master`. Acceptance: `max(date) = 2026-10-23` on `mkt_nse_full_daily`, `mkt_bse_eq_daily`, `mkt_bse_delivery_daily`, `mkt_nse_index_daily`, `mkt_bse_index_daily`, `mkt_nse_deals`, `mkt_bse_deals`, `mkt_fii_dii_cash`, `mkt_nsdl_fpi_daily`, `mkt_circuit_*`.
4. **Rebuild `daily_price_delivery` for 2019 → 2026-10-23.** This is the harness's price table and it is both short (2021-10-27 start) and stale (2026-09-24). Either extend `pipeline/backfill.py` to promote the full `mkt_*` history, or point `validation_harness` / `desk_backtest` / `composite_screener` at `px_daily`. **Acceptance: a 2021-01-01 start date is reachable and the last session is 2026-10-23.** Do not start testing until this passes.
5. **Rebuild the truth snapshot** (`build_truth_snapshot`) and re-run the gate `python -m reality_engine.scripts.coverage_report` + `cli audit-data`. Acceptance: one snapshot for 2026-10-23, coverage report shows every traded stock per year 2019→2026 with price coverage and the four gaps below closed.

**P1 — close the holes that make 2019→today incomplete**

6. **PIB English gap 2025-12-20 → 2026-09-24**: `python -m reality_engine.scripts.pib_feed --start 2025-12-20 --end 2026-09-24`, then resume daily (`--start <D-3>`). *No GPU; ~20 min/day, ≈9 months ≈ 3–4 h.*
7. **`circuit_hits` / `price_bands`**: either re-run `fetch_nse_pr --start 2026-09-23` (raw zips were lost, so it re-downloads) or copy the fuller tables out of `truth_2026-10-19.duckdb`. Then confirm the post-restore content of every table written after 2026-10-19 16:50.
8. **Insider path**: decide one source of truth. `insider_trades` (0 rows, what `get_recent_insider_trades` reads) vs `mkt_nse_pit_filings`/`mkt_nse_insider` (current to 2026-10-16 / 2026-05-02). Load `insider_trades` from `mkt_nse_pit_xbrl_facts` before any smart-money hypothesis is tested.
9. **Point-in-time index membership** (`index_membership` is one 2026-09-30 snapshot of 3 indices) — survivorship and index-membership bias will invalidate any universe-conditioned test. Needs NSE/BSE historical constituent files.
10. **Breadth series**: `backfill_index_ohlc` (2026-09-24) and `financially_free_breadth` (empty). Pick one and run it 2019→today, or drop the feature deliberately.
11. **Commodity series** to today (`mkt_commodity_daily` 2026-10-06, `_monthly` 2025-12).
12. **BSE announcements / corporate actions / board meetings / security master** — just the last 5 sessions, via one successful `run_eod_market`.
13. **Fix `backup_dbs_to_drive`** (PermissionError on `data/logs/db_backup.log`; incomplete set 2026-10-19) — otherwise the next restore repeats finding 4.

**P2 — document corpus (needed for fundamentals, cost/quota-bound)**

14. **Re-establish the PDF corpus** (`data/pdfs`, `data/macro_pdfs`, `Deck`/AR files are empty here) with `run_filing_download.cmd both` + `fetch_decks.py` — **$** (network + free-reader quotas only; storage ~150–200 GB).
15. **Deck figure extraction** resume (`run_deck_extract.cmd`, 815k pages / 13.57M facts today) — **$ free reader quotas**; needs a reader health check first (Beam 3.9% broken JSON, MiniMax retries, `STATE.md:39`).
16. **AR fact extraction** resume (`run_ar_ingest.cmd` / `run_ar_google.cmd`) — **$ free tiers**; 3,520 of ~33k reports chunked. Only after the AR study settles indexing (`tasks/ANNUAL_REPORT_VALUE_STUDY.md`).
17. **Concall extraction for Q2 FY27** (`run_concall_deepseek.cmd`) — **$ OpenCode Go quota**; 2026 set complete to 2026-10-14.
18. **Weekly SEBI / offer documents** (`run_weekly_sebi_ingest.cmd`) — **$ embedding API**; 909 docs, last 2026-09-17.
19. **News loop** — decide whether it exists at all: no log has ever been produced by `run_news_loop.cmd`; either install `RealityEngine-NewsLoop`, or delete the job.

**P3 — make it impossible to forget again (that is Phase 2)**

20. Populate `plugins/dsh-worker/jobs.yaml` from this audit with a **success check per job** that is a SQL freshness query, not an exit code — specifically: `max(date)` for every `mkt_*` table, `max(release_date)` for `pib_days`, `max(d)` for `daily_price_delivery`, `count(*) > 0` for `insider_trades`/`financially_free_breadth`. `run_eod_market` returning 0 while loading nothing (finding 1) is the exact class of bug this must catch.

## 7. Explicitly unverified

- Live Task Scheduler: `RealityEngine-BootRecover`, `-EODMarket`, `-DBBackup`, `-DeepSeekHeartbeat`, `-AnnualDrain`, `-CapacityLoop`, `-ContinuousLoop`, `-ForecastTester`, `-NewsLoop`, `-Routines`, `RealityEngine_WeeklySEBIIngest` — names verified from code/`.cmd`; **enabled/disabled, LastRunTime and LastResult unverified** (CIM + registry blocked). STATE.md asserts all are disabled since 2026-10-21 01:30.
- Whether any job is running *right now* (no log activity after 2026-10-21 14:38).
- Root cause of the 2026-10-20 `missing: 1` on all eight exchange sources.
- Whether `run_eod_market` ran on 2026-10-21/22/23 at all — no `eod_market.log` exists in the live log dir, and the archived copy ends 2026-10-20 21:14. Its absence is strong evidence it did **not** run, but the log could also have been moved.
- `pib_backfill.log` referenced throughout `STATE.md` does not exist in either the live or the archived log dir; PIB progress is therefore inferred from `pib_days`/`pib_releases` only.
- Whether the 2026-10-21 restore overwrote more than `circuit_hits`/`price_bands` (only those two show a regression against the 2026-10-19 snapshot).
- `fetch_missed_ar_files.py`, `run_offer_drhp_backfill.py`, `run_offer_pdf_resolve.py`: no log evidence found — **unknown**.

---

*skipped: live Task Scheduler query (sandbox blocks CIM/registry — marked unverified rather than guessed). Add when a session can run `schtasks /query /fo LIST /v` with normal access: the enabled/LastResult columns for the 11 task names above.*
