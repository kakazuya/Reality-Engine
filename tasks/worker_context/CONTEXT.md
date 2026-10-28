# Worker context pack

Generated: 2026-10-29T01:21:03+05:30 · git HEAD: `82a2ae5` · data root: `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data`
Staleness: regenerate with `python -m reality_engine.scripts.build_worker_context`; the `worker_context` job runs daily and a pack older than 26 h is regenerated before a worker starts.
Read this once. It replaces file-by-file orientation; the task brief is still the authority for what to do.

## 1. Repo map

Top-level tree to depth 2 (tests/fixtures skipped):
```
reality_engine/
  agent/ (4 py) — Agent module for Reality Engine.
  db/ (9 py) — Database services.
  harness/ (28 py) — Shared, point-in-time research harness. Importing never opens a database.
  ingestion/ (27 py) — Reality Engine Ingestion Subsystem
  pilot/ (5 py) — Pilot builds (golden-rule step 4). Deterministic tier: ``build_t1``; checks: ``checks_t1``.
  pipeline/ (19 py) — Pipeline runners.
  processing/ (45 py) — Document and image processing components.
  query/ (18 py) — Query layer v1 — sub-question decomposition + router + planners + answer assembly.
  reporting/ (3 py) — Reporting module for Reality Engine.
  scripts/ (145 py) — Operational job scripts: one module per data job; most-referenced list below
  search/ (4 py) — Search services.
  toolbelt/ (12 py) — Ready-made, read-only tools for dsh workers (Task 02).
  ui/ (2 py) — Reality Engine UI Module.
plugins/
  code-intel/ (3 py) — code-intel: LSP-backed code intelligence over the reality-engine checkout.
  data-gather/ (3 py) — Feed metadata and read-only probes.
  dsh-worker/ (12 py) — Job manager for the local dsh-worker Codex plugin.
  reality-data/ (9 py) — Data access core for the reality-data MCP server.
tasks/
analysis/ (27 entries) — Annual-report PIT labels from the BSE filename (additive, idempotent). No network.
```

Module one-liners (first docstring line, clipped; `__init__.py` and modules without a docstring skipped):

### plugins/code-intel/server/
- `plugins/code-intel/server/core.py` — code-intel: LSP-backed code intelligence over the reality-engine checkout.
- `plugins/code-intel/server/lsp.py` — Minimal JSON-RPC/LSP client for one long-lived ``basedpyright-langserver``.
- `plugins/code-intel/server/server.py` — code-intel MCP server (stdio).

### plugins/data-gather/server/
- `plugins/data-gather/server/feeds.py` — Feed metadata and read-only probes.
- `plugins/data-gather/server/gather.py` — Feed orchestration for the data-gather MCP server.
- `plugins/data-gather/server/server.py` — MCP stdio surface for the data-gather plugin.

### plugins/dsh-worker/server/
- `plugins/dsh-worker/server/context_pack.py` — Worker context pack: attach the generated repo/data map to every brief.
- `plugins/dsh-worker/server/core.py` — Job manager for the local dsh-worker Codex plugin.
- `plugins/dsh-worker/server/dsh_worker_mcp.py` — Entry point for the local dsh-worker MCP stdio server.
- `plugins/dsh-worker/server/gitutil.py` — Bounded git helpers: working-tree snapshots, worktrees and auto-commit.
- `plugins/dsh-worker/server/heartbeat.py` — Integration with the dsh heartbeat supervisor's actual control contract.
- `plugins/dsh-worker/server/jobs.py` — Data-job registry: ``jobs.yaml`` loading, validation and freshness checks.
- `plugins/dsh-worker/server/plugin_server.py` — MCP stdio surface for the dsh-worker plugin.
- `plugins/dsh-worker/server/procutil.py` — Windows process helpers for owned worker processes.
- `plugins/dsh-worker/server/progress.py` — Bounded, incremental progress from a dsh ``--json`` event stream.
- `plugins/dsh-worker/server/store.py` — Small, dependency-free persistence helpers for the local dsh worker plugin.
- `plugins/dsh-worker/server/supervisor.py` — Detached supervisor for one dsh job.

### plugins/reality-data/server/
- `plugins/reality-data/server/catalog.py` — Catalog of the reality-engine data map.
- `plugins/reality-data/server/core.py` — Data access core for the reality-data MCP server.
- `plugins/reality-data/server/dense_free.py` — Free dense retrieval over the stored, already-paid embedding indexes.
- `plugins/reality-data/server/lookups_docs.py` — One-call document lookups across the five document stores.
- `plugins/reality-data/server/lookups_market.py` — One-call market lookups: ``delivery``, ``price_extreme``, ``holding``.
- `plugins/reality-data/server/query_embed.py` — Query-time embeddings for the 4096-d vector indexes.
- `plugins/reality-data/server/search_docs.py` — Hybrid document search over the Reality Engine data root.
- `plugins/reality-data/server/server.py` — reality-data MCP server (stdio).
- `plugins/reality-data/server/universe.py` — Point-in-time theme universes.

### reality_engine/
- `reality_engine/cli.py` — Reality Engine CLI Tool
- `reality_engine/config.py` — Configuration Module for Reality Engine (Phase 1)
- `reality_engine/raw_store.py` — Content-addressed raw store: identical bytes are stored once (sha256 + hard links).

### reality_engine/agent/
- `reality_engine/agent/orchestrator.py` — Agent Orchestrator Module
- `reality_engine/agent/schemas.py` — Agent Schemas Module
- `reality_engine/agent/tools.py` — Agent Tool Registry & Dispatcher Module

### reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/apply_annual_report_pit.py` — Annual-report PIT labels from the BSE filename (additive, idempotent). No network.
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/apply_bse_join.py` — Join corporate_documents to the harvested BSE announcement feed by PDF name (additive, idempotent).
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/apply_pit_repair.py` — Apply analysis/proposed_changes.csv to corporate_documents (additive, reversible).
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/bse_announcement_harvest.py` — Harvest BSE corporate-announcement metadata (exact dissemination timestamps) into a SEPARATE sqlite.
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/bse_harvest_missing.py` — List equity-ISIN symbols whose BSE harvest is incomplete (any year-window missing in `done`).
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/build_snapshot_and_proposal.py` — Build the reversible change set for the crawl-date defect.
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/export_parquet.py` — Export the analysis-ready tables to Parquet (chunked, low memory) -> reality_engine/data/parquet/.
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/extract_call_date.py` — Extract the real (call-date, filing-date) pair from a BSE/NSE Reg-30 earnings-call
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/make_sample_db.py` — Build a small, public-data-only sample of the live DB so the code can be run on another machine befo …
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/overnight_part2.py` — Queue behind overnight_pipeline.py: starts when its step 8 is done (or it has failed/finished), so t …
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/overnight_pipeline.py` — Overnight chain (resumable via analysis/overnight_state.json). Each step is isolated: a failure is l …
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/package_for_drive.py` — Build the Drive upload pack in C:/pack_drive (originals untouched):
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/run_extract_all.py` — Run the call-date extractor over every processed concall and emit a reviewable
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/secrets_scan.py` — Scan files git would publish (tracked + untracked-not-ignored, text, <2MB) for likely secrets.
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/tariff_event_study.py` — Tariff event study per tasks/tariff_event_card_2026-09-29.md. Read-only on the DB.
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/tg_collect_video_links.py` — Collect YouTube links from selected Telegram forum topics (read-only) -> analysis/tg_video_links.csv …
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/video_load_loop.py` — Loop: load every finished transcript into the DB (frames+OCR+chunks) until all 65 batch videos are l …
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/video_transcribe_batch.py` — Transcribe finished videos from analysis/yt_batch_3mo.txt with whisper.cpp (Vulkan, RX 6700 XT).
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/yt_download_batch.py` — Download the batch listed in analysis/yt_batch_3mo.txt (newest first): <=1080p video+audio -> realit …
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/yt_probe.py` — Metadata-only probe (no download): duration + availability for each unique video. -> analysis/yt_pro …

### reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/01_build_events.py` — Build the event table: BSE announcements (exact DissemDT, IST) -> (isin, t0 session, timing bucket, …
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/02_event_engine.py` — Vectorised market-model event study over every event-day (read-only on inputs).
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/03_estimate.py` — Stratum-level estimation for the price-side information-diffusion study (numpy/pandas only).
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/04_negative_reaction_matched.py` — Negative-reaction puzzle, test 1 (closeout 2026-10-05 §3): do matched NON-announcers with the same p …
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/05_negative_reaction_splits.py` — Negative-reaction puzzle, test 3 (closeout 2026-10-05 §3): is the announcer-vs-matched-control gap i …
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/common.py` — Shared constants for the price-side information-diffusion study (read-only on all databases).

### reality_engine/data/backups/drive_processed_2026-10-21/processed_data/concall_pilot/gemma_v3/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/concall_pilot/gemma_v3/run_pilot.py` — Gemma 4 vs MiniMax on 10 transcripts, prompt v3 + machine_check (Shivam 2026-10-20 'run it'). Free G …

### reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/probe_lib.py` — Throwaway network probe harness. Read-only, no DB writes, no repo source edits.

### reality_engine/data/backups/restore_2026-10-21/
- `reality_engine/data/backups/restore_2026-10-21/restore_databases.py` — Audited, local-only restore of the two final PC exports. No snapshot writes.

### reality_engine/data/embed_test/
- `reality_engine/data/embed_test/colab_embed_test.py` — Colab side of the embedding retrieval test (2026-10-19, Shivam: is Qwen3-Embedding-8B worth it vs ge …

### reality_engine/data/logs/
- `reality_engine/data/logs/date_resolver_coverage.py` — Coverage of the text date resolver on the 1,499 undated concall transcripts (2026-10-24 patch check) …
- `reality_engine/data/logs/dsh_plugin_overnight_audit.py` — Read-only installed MCP audit. Never starts an inference worker.
- `reality_engine/data/logs/probe_lanes_20261024.py` — One-off lane probe for the concall-reader patch (2026-10-24): Go key 1/2 Beam + LongCat on both Go e …
- `reality_engine/data/logs/run_provider_probes.py` — Small authorized live probes. Logs controls/usage, never credentials or reasoning text.

### reality_engine/data/logs/dsh_heartbeat_bootstrap/
- `reality_engine/data/logs/dsh_heartbeat_bootstrap/run_deepseek_harness.before.py` — Run one task headlessly in DeepSeek Harness (dsh) on an OpenCode Go model, so a Claude orchestrator …
- `reality_engine/data/logs/dsh_heartbeat_bootstrap/test_deepseek_harness_controls.before.py` — Local checks only: no credentials, subprocesses, inference or database access.

### reality_engine/db/
- `reality_engine/db/bootstrap.py` — Reality Engine Database Bootstrap Module
- `reality_engine/db/database.py` — Database Engine Module
- `reality_engine/db/fixtures.py` — Test Fixture & Isolation Utilities Module
- `reality_engine/db/migrate_master_isin.py` — Phase 1 Slice 3: Master ISIN anchor dual-write check — SQLite WAL → PG companies(isin PK)
- `reality_engine/db/readonly.py` — Read-only SQLite connections with a per-statement wall-clock guard.
- `reality_engine/db/repository.py` — Repository Module
- `reality_engine/db/seed_fundamental.py` — Seed countries + industries for Fundamental Reality Engine — PG primary, SQLite fallback demo.
- `reality_engine/db/vector_store.py` — LanceDB-backed vectors with a dependency-free JSON/NumPy fallback.

### reality_engine/harness/
- `reality_engine/harness/adapter.py` — Schema-checked adapter for the sole authorized dated snapshot.
- `reality_engine/harness/benchmark.py` — B5 selection frozen before each month, using strictly earlier TRI data.
- `reality_engine/harness/book.py` — Daily cash book over one predeclared long H01 variant.
- `reality_engine/harness/costs_tax.py` — Fixed 30 bp return debit and sell-date tax, with no live DB access.
- `reality_engine/harness/coverage.py` — Year-by-year subset coverage. Missing data never become a zero feature.
- `reality_engine/harness/data.py` — Snapshot-only data access; no live database imports or connections.
- `reality_engine/harness/execution.py` — Executable dates/prices; no stale quote substituted at either endpoint.
- `reality_engine/harness/inspect_snapshot.py` — Read-only schema and small metadata audit. No joins before DESCRIBE.
- `reality_engine/harness/ledger.py` — The only writable database: append-only variant audit ledger.
- `reality_engine/harness/run_h01.py` — Run H01's eight variants under both reviewed PIT timing policies.
- `reality_engine/harness/run_h01_long.py` — Declared longer-horizon H01 grid; separate outputs, same shared harness.
- `reality_engine/harness/run_h01_selection.py` — Ten declared stock-selection contrasts after the H01 timing extension.
- `reality_engine/harness/run_h01_wall.py` — H01 fall chronology and eight declared downside-control books.
- `reality_engine/harness/run_h01xh02.py` — Stage 2: declared H01 x H02 combinations C1-C6.
- `reality_engine/harness/run_h02.py` — Run H02 Card F exactly as declared, before any outcome is inspected.
- `reality_engine/harness/stats.py` — Full-grid FDR, month-cluster inference and reproducible date placebos.
- `reality_engine/harness/universe.py` — U1 filtering, independent of today's active/listed flag.
- `reality_engine/harness/verify_h01.py` — Independent artifact/source checks for the reviewed H01 rerun.
- `reality_engine/harness/verify_h01_long.py` — Independent longer-horizon artifact/source review; no inference/live DB.
- `reality_engine/harness/verify_h01_selection.py` — Independent pandas/source verification of the ten selection contrasts.
- `reality_engine/harness/verify_h01_wall.py` — Source, FIFO, chronology and executable-price review of the H01 wall.
- `reality_engine/harness/verify_h01xh02.py` — Independent Stage 2 verification of the declared C1-C6 combination.
- `reality_engine/harness/verify_h02.py` — Independent H02 verification: different queries and arithmetic paths.

### reality_engine/harness/cards/
- `reality_engine/harness/cards/h01_pead.py` — H01 Card B: PIT earnings surprise on normalized snapshot facts.
- `reality_engine/harness/cards/h02_combine.py` — H01 x H02 combination rules, fixed before Stage 2 is run.
- `reality_engine/harness/cards/h02_deals.py` — H02 Card F: bulk/block deal accumulation, point-in-time from the snapshot.

### reality_engine/ingestion/
- `reality_engine/ingestion/bse_client.py` — BSE Ingestion Client Module
- `reality_engine/ingestion/bse_fundamentals_client.py` — BSE fundamentals client: financials, shareholding, sector identity, announcements.
- `reality_engine/ingestion/bulk_fetch_template.py` — Bulk Fundamentals Fetch Template
- `reality_engine/ingestion/content_classifier.py` — Method C Content Classifier — post-download CPU fitz + GPU OCR fallback (DirectML RX 6700 XT).
- `reality_engine/ingestion/corporate_actions_client.py` — Corporate Actions Ingestion Client — official NSE corporate-actions feed.
- `reality_engine/ingestion/deals_client.py` — NSE bulk/block deals ingest (Tier-0 news feed).
- `reality_engine/ingestion/delisting_nclt_client.py` — Delisting / NCLT (Insolvency) Status Client.
- `reality_engine/ingestion/filing_discovery.py` — Filing Discovery Module — Screener raw-link discovery layer.
- `reality_engine/ingestion/financially_free_client.py` — FinanciallyFree Market Breadth Ingestion Client Module (Layer 3)
- `reality_engine/ingestion/fundamentals_client.py` — Fundamentals Ingestion Client Module
- `reality_engine/ingestion/headless_fetcher.py` — Headless Browser JWT / Cookie Fetcher for blocked BSE/NSE endpoints
- `reality_engine/ingestion/llm_lens_client.py` — Local LLM lens-extraction backend over a llama.cpp OpenAI-compatible server.
- `reality_engine/ingestion/macro_pdf_fetcher.py` — Macro PDF Fetcher for Reality Engine (second-tier peer data below core company data)
- `reality_engine/ingestion/master_sync.py` — Master Company Synchronization Module
- `reality_engine/ingestion/news_announcements_client.py` — NSE corporate-announcements ingest (Tier-0 news feed).
- `reality_engine/ingestion/news_feed_client.py` — Official-outlet broad-market RSS ingest (Tier-1 news feed).
- `reality_engine/ingestion/nse_client.py` — NSE Ingestion Client Module
- `reality_engine/ingestion/official_filing_client.py` — Official Filing Client — downloads & archives raw NSE/BSE filings.
- `reality_engine/ingestion/official_financials_client.py` — Official Financials Client — source-resolver for canonical NSE/BSE numeric financials.
- `reality_engine/ingestion/onnx_embedder.py` — Local ONNX embedding backend on DirectML (RX 6700 XT) with CPU fallback.
- `reality_engine/ingestion/pdf_ingestor.py` — Layout-aware PDF ingestor for Fundamental Reality Engine.
- `reality_engine/ingestion/policy_press_client.py` — Probe-forward press-release fetchers for PIB + RBI (Tier-1 news-feed v1).
- `reality_engine/ingestion/resource_guard.py` — Adaptive system-load guard for bounded local document ingestion.
- `reality_engine/ingestion/sebi_offer_client.py` — SEBI offer-document client: DRHP / Prospectus discovery + PDF resolution.
- `reality_engine/ingestion/telegram_client.py` — Telegram MTProto Ingestion Client Module (Layer 3)
- `reality_engine/ingestion/youtube_transcriber.py` — YouTube / MP4 transcription wrapper for Fundamental Reality Engine.

### reality_engine/pilot/
- `reality_engine/pilot/build_t1.py` — T1 (deterministic) pilot build — PILOT_SPEC §3 deterministic tier, SCHEMA_V3 §B/§C.
- `reality_engine/pilot/checks_t1.py` — Checks for the T1 pilot build — the numbers behind tasks/pilot_t1/CHECKS.md.
- `reality_engine/pilot/macro_claims.py` — macro_claim_target pilot (G10 / policy_target) — deterministic claim -> target map.
- `reality_engine/pilot/universe60.py` — Stratified 60-company pilot universe (golden-rule step 4, tasks/pilot60).

### reality_engine/pipeline/
- `reality_engine/pipeline/backfill.py` — Historical Backfill Pipeline Module
- `reality_engine/pipeline/bootstrap.py` — Deterministic Bootstrap & Test-Data Seeding Pipeline Module
- `reality_engine/pipeline/bse_backfill.py` — BSE Bhavcopy Backfill Pipeline Module
- `reality_engine/pipeline/capacity_loop.py` — Capacity loop — scheduled explainer-capacity governor (report-only by default).
- `reality_engine/pipeline/catchup_scheduler.py` — Missed-Days Catcher + Twice-Daily Scheduler
- `reality_engine/pipeline/continuous_loop.py` — Continuous Loop — 30-minute harness check + unattended agent iteration pass.
- `reality_engine/pipeline/data_audit.py` — Data Pipeline Readiness Audit
- `reality_engine/pipeline/forecast_tester.py` — Forecast Tester — scheduled price-action forecast testing (Wave B driver).
- `reality_engine/pipeline/inbox_runner.py` — Local-first drop-in inbox ingestion pipeline.
- `reality_engine/pipeline/macro_runner.py` — Macro ingestion orchestrator for the Fundamental Reality Engine.
- `reality_engine/pipeline/news_loop.py` — News loop — scheduled daily news ingest + infographic capture + prune.
- `reality_engine/pipeline/news_retention.py` — News retention — "extract the info, then delete the papers" (fail-closed).
- `reality_engine/pipeline/nightly_alpha.py` — Wave A — Unattended Nightly Run Chain (fetch -> predict -> correct -> track).
- `reality_engine/pipeline/nightly_runner.py` — Nightly Runner (thin wrapper over the missed-days catcher).
- `reality_engine/pipeline/offer_backfill.py` — SEBI offer-document backfill pipeline: listing crawl -> match -> archive -> distill.
- `reality_engine/pipeline/panic_monitor.py` — Panic Monitor Module
- `reality_engine/pipeline/phase1_runner.py` — Phase 1 End-to-End Execution Pipeline
- `reality_engine/pipeline/routines.py` — Clock-time Oh My Pi routines (Claude Code local-schedule analog).

### reality_engine/processing/
- `reality_engine/processing/ar_row_guards.py` — Guards for the annual-report row clean-up pass (tasks/AR_INGESTION_PROTOCOL.md, LLM stage a).
- `reality_engine/processing/attention_ranker.py` — Tier-3 attention ranking + morning digest (news-feed Tier-2/3 slice).
- `reality_engine/processing/business_peer_graph.py` — Business-substance cross-map: analog companies by what they actually do.
- `reality_engine/processing/business_profiler.py` — Wave A2 (Task A2): Business Model Profiles canonical persistence.
- `reality_engine/processing/capacity_governor.py` — Capacity governor — evidence-gated explainer-capacity expansion.
- `reality_engine/processing/causal_engine.py` — SQLite-backed causal knowledge graph operations.
- `reality_engine/processing/chunker_v2.py` — C1: structure-aware chunking.
- `reality_engine/processing/chunker_v3.py` — chunker_v3 — documents to searchable chunks (spec: tasks/ARCHITECTURE_OVERHAUL_2026-10-27 §2.2/§3/§4 …
- `reality_engine/processing/composite_screener.py` — Composite Quantitative Screener & Factor Model Module
- `reality_engine/processing/desk_backtest.py` — Desk backtest — Rs 10cr Oct-2021 lump-sum book + 4x4 excess harness.
- `reality_engine/processing/distillation_engine.py` — Structured, queryable company-parameter distillation store.
- `reality_engine/processing/distillation_pruner.py` — Pillar 4: LLM Knowledge Distillation before deletion — monthly batch synthesis.
- `reality_engine/processing/document_parser.py` — Digital/scanned document extraction and financial transcript chunking.
- `reality_engine/processing/ensemble_ranker.py` — Wave D1 — Sparse, revisable reasoning: MoE ensemble_ranker.
- `reality_engine/processing/entity_graph.py` — Unified entity cross-map: ONE place that answers A + B + C together.
- `reality_engine/processing/eod_corrector.py` — Wave D3 — Continuous Self-Correction (EOD + Event).
- `reality_engine/processing/event_graph.py` — Wave D2 — Transient Event-Graph Spawner.
- `reality_engine/processing/factor_loaders.py` — Factor loaders — fetch the external series the factor spine is missing.
- `reality_engine/processing/factor_spine.py` — Factor spine — dated, point-in-time-correct factor series (design §1-§2).
- `reality_engine/processing/financial_validator.py` — Task 7: Financial secondary validation ROIC>WACC spread>0.05 only after moat/policy
- `reality_engine/processing/fundamental_engine.py` — Fundamental Processing Engine Module
- `reality_engine/processing/instrument_classifier.py` — Instrument Classifier — Dense-substrate denominator filter
- `reality_engine/processing/layout_gpu.py` — C1b: GPU layout detection for annual reports (GTX 1050 Ti, 4 GB).
- `reality_engine/processing/macro_simulator.py` — Macro shock propagation over the causal graph.
- `reality_engine/processing/moat_scorer.py` — Wave A2 (Task A2): Moat rubric Moat=0.25*SC+0.25*NE+0.20*CA+0.20*IA+0.10*ES (0-5).
- `reality_engine/processing/move_attributor.py` — Slice 1 — Move attribution ledger (tasks/next_wave_attribution.md §2 Slice 1).
- `reality_engine/processing/news_explainer.py` — News explainer: read-only move attribution over Tier-0 tables (news-feed v1).
- `reality_engine/processing/news_extractor.py` — News extractor: structured extraction + importance ranking + brief builder.
- `reality_engine/processing/news_vision.py` — News infographic capture — RSS media -> download -> OCR -> FTS chunk + artifact row.
- `reality_engine/processing/ocr_engine.py` — Optional-accelerated OCR with deterministic financial entity extraction.
- `reality_engine/processing/peer_graph.py` — Analog peer graph — precomputed nearest neighbours over the dense substrate.
- `reality_engine/processing/policy_engine.py` — Wave B1 (Task B1): Policy ENI peer — canonical dense-substrate persistence.
- `reality_engine/processing/portfolio_ledger.py` — Slice 3 — Portfolio/ROC ledger + calibration feedback
- `reality_engine/processing/pruning_engine.py` — 4-Pillar Data Pruning & Lifecycle Framework - Exponential Decay & Graph Pruning.
- `reality_engine/processing/rumor_backfill.py` — Telegram -> FTS backfill: index telegram_posts rows into intelligence_fts (news-feed Tier-2).
- `reality_engine/processing/rumor_scorer.py` — Rumor corroboration scorer over Tier-2 FTS rows (news-feed Tier-2).
- `reality_engine/processing/sip_backtest.py` — Tax-aware SIP backtest — Nifty-50 equal-weight benchmark leg (Slice: SIPBench).
- `reality_engine/processing/sip_signals.py` — SIP signal legs (Leg A / Leg B) over the shared SIP/tax/metrics engine.
- `reality_engine/processing/skill_loop.py` — Self-improving forecast loop: score → fit → apply → re-score, walk-forward.
- `reality_engine/processing/substrate_hygiene.py` — Substrate trust layer — isolates rows that must never be served as production evidence.
- `reality_engine/processing/technical_engine.py` — Technical Processing Engine Module
- `reality_engine/processing/validation_harness.py` — Wave B — Model-testing loop: score past predictions vs realized prices.
- `reality_engine/processing/video_screen_ocr.py` — Video screen OCR pilot (CPU): 5 s frames -> thumbnail dedupe -> RapidOCR -> labelled screens.
- `reality_engine/processing/vision_engine.py` — Multimodal Vision Alpha Pipeline - keyframe extraction + VisualArtifact schema.

### reality_engine/query/
- `reality_engine/query/answer.py` — Assemble the hops into one structured answer, or the NOT-IN-DATA wording.
- `reality_engine/query/compute.py` — Pure arithmetic for the query layer: no I/O, no globals.
- `reality_engine/query/ctx.py` — Query context: read-only connections and the tool handles the planners use.
- `reality_engine/query/decompose.py` — Split one master-bank case into sub-questions, deterministically.
- `reality_engine/query/rerank.py` — Cheap local reranker for EVIDENCE passages (no embeddings, no network).
- `reality_engine/query/router.py` — Deterministic router: a master-bank case -> planner chain + slots.
- `reality_engine/query/state.py` — One query entry point (PIPELINE_TODO Q4, first version 2026-10-19): everything known about a company …

### reality_engine/query/planners/
- `reality_engine/query/planners/compare.py` — COMPARE: the same metric or window return over a peer set, ranked.
- `reality_engine/query/planners/event.py` — EVENT: what was known at T and how the session(s) around it moved.
- `reality_engine/query/planners/evidence.py` — EVIDENCE: passages from the company's own documents, PIT-filtered in SQL.
- `reality_engine/query/planners/expectations.py` — EXPECTATIONS gate: judgement asks have no held store, and must say so.
- `reality_engine/query/planners/facts.py` — FACTS: one metric (+period) from every stamped fact store, PIT-filtered in SQL.
- `reality_engine/query/planners/resolve.py` — RESOLVE: canonical identity at ``as_of`` (never today's symbol).
- `reality_engine/query/planners/ripple.py` — RIPPLE: trigger -> exposure -> transmission -> market, stopping at the gap.
- `reality_engine/query/planners/screen.py` — SCREEN: rank a held universe on one dated metric (or name the missing table).
- `reality_engine/query/planners/series.py` — SERIES: dated price/index/commodity rows plus the arithmetic the ask names.

### reality_engine/reporting/
- `reality_engine/reporting/notifier.py` — Wave B — Telegram alerts + 23:00 nightly digest (stdlib only, no new deps).
- `reality_engine/reporting/writer.py` — Report Writer Module

- `reality_engine/scripts/` — 145 data-job modules (one per data job); most-referenced ranked below.
### reality_engine/search/
- `reality_engine/search/chunk_vector_index.py` — Local dense-retrieval index over ``document_chunks.embedding``.
- `reality_engine/search/hybrid_search.py` — Lexical plus dense search using reciprocal rank fusion.
- `reality_engine/search/intel_search.py` — Tier-aware unified search over ``intelligence_fts`` (news-feed v1).

### reality_engine/toolbelt/
- `reality_engine/toolbelt/_common.py` — Shared helpers for the toolbelt CLIs.
- `reality_engine/toolbelt/cost_ledger.py` — Append-only paid-call ledger with a hard budget gate.
- `reality_engine/toolbelt/coverage_peek.py` — One command: what data do we hold for a symbol, per store, with row counts and date ranges.
- `reality_engine/toolbelt/drive_fetch.py` — Fetch a document from ``gdrive:InfoDiffusion_archive`` by path, sha256 or stale DB path.
- `reality_engine/toolbelt/find_docs.py` — Find a company's documents across every store and report their real state.
- `reality_engine/toolbelt/job_peek.py` — Compact view of a dsh job directory without loading whole event files.
- `reality_engine/toolbelt/lookup_docs.py` — CLI for the one-call document lookups (same functions as the MCP tools).
- `reality_engine/toolbelt/lookup_market.py` — One-call market lookups from the shell (same functions the MCP tools expose).
- `reality_engine/toolbelt/mod_test.py` — Run a Claude Code mod's checks the way this sandbox actually allows.
- `reality_engine/toolbelt/render_pages.py` — Render PDF pages to PNG, or dump the text layer with the pipeline's low-text rule.
- `reality_engine/toolbelt/sample_rows.py` — Random row samples from a live SQLite store without scanning it.

### reality_engine/ui/
- `reality_engine/ui/dashboard.py` — Reality Engine - Streamlit Equity Intelligence Dashboard

### Most-referenced scripts

Ranked by mentions in `tasks/STATE.md`, `plugins/dsh-worker/jobs.yaml` and the 20 newest `tasks/dsh_tasks/*.md` briefs:

- `reality_engine/scripts/ar_queue.py` (23 refs) — Annual-report work queue for readers that only answer inside the OpenCode app (OpenCode Zen free models).
- `reality_engine/scripts/ingest_annual_reports.py` (16 refs) — Annual-report fact extraction with the free readers that passed the AR must-find test (tasks/ar_study/free_test):
- `reality_engine/scripts/results_notes.py` (14 refs) — Quarterly results PDFs -> notes chunks, one fiscal quarter at a time (newest first), with a gate per quarter.
- `reality_engine/scripts/resource_watchdog.py` (12 refs) — Machine-wide resource watchdog: keeps the long jobs alive and records every case of wasted compute.
- `reality_engine/scripts/boot_recover.py` (10 refs) — Crash recovery: bring every job back after a reboot or power cut, with nobody logged in (Shivam 2026-10-19).
- `reality_engine/scripts/concall_deepseek.py` (8 refs) — 2026 concall transcripts -> DeepSeek V4.1 Flash on OpenCode Go (Shivam, 2026-10-18: 2026 transcripts are read by
- `reality_engine/scripts/extract_deck_figures.py` (8 refs) — Extract the figures printed on investor-presentation slides with OpenCode Go vision models.
- `reality_engine/scripts/new_reader_check.py` (8 refs) — Daily check for new free readers (STATE to-do 1, 2026-10-13). Run once a day by the resource watchdog; safe to run
- `reality_engine/scripts/nse_announcements.py` (7 refs) — NSE corporate-announcements raw fetcher (one symbol at a time, resumable).
- `reality_engine/scripts/deepseek_heartbeat.py` (6 refs) — DeepSeek heartbeat (Shivam, 2026-10-20): wakes DeepSeek, never Claude. Run hourly by the Windows task
- `reality_engine/scripts/pib_regional.py` (6 refs) — PIB phase 2 (PIPELINE_TODO A2, 2026-10-19): Hindi / Urdu releases of PIB Delhi and every regional PIB office in every
- `reality_engine/scripts/claude_page_queue.py` (5 refs) — Hand-off between the deck-figure database and Claude Code helper agents (Claude Haiku 5.5), which cannot be called

### Tools

- Toolbelt (`reality_engine/toolbelt/README.md`; `python -m reality_engine.toolbelt.<tool>`, read-only): `coverage_peek --symbol X`, `find_docs --symbol X`, `sample_rows --db <db> --table <t> --n 5`, `job_peek <job>`, `render_pages --pdf <f> --pages 3,5-7`, `drive_fetch`, `cost_ledger`, `mod_test`.
- Code-intel MCP (`mcp__code-intel__*`) — use before grep: `module_map(package)`, `symbols(file= | query=)`, `definition(symbol)`, `references(symbol)`, `callers(fn)`, `hover(file,line)`, `diagnostics(files= | changed=True)`.

## 2. Data map

Data root: `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data` (`REALITY_DATA_ROOT`; read-only from a worktree). Never write without an explicit instruction.

| DB | file | size | tables | use |
|---|---|---|---|---|
| truth_duckdb | `truth_2026-10-19.duckdb` | 8.5 GB | 63 | Dated, read-only research snapshot (2026-10-19) built from the live SQLite DBs: clean entity-level prices with split/bonus/dividend adjustment and point-in-time known_at timestamps (date-only sources stamped 23:59:59 IST), plus consolidated results/AR/deck/concall/ownership/policy tables. Prefer this for historical/as-of research; SQLite is the live source with newer rows and full text. |
| equity_intelligence | `equity_intelligence.db` | 50.3 GB | 123 | Live primary equity database: company master, normalized daily prices, financials, corporate actions/documents, ownership/market flows, policy/macro/ripple layers, substrate analytics, Telegram signals and quarantine. Use it for latest/live data and full text; use truth_duckdb for adjusted price history and PIT-stamped research tables. Mixed raw and derived; check per-table notes. |
| ar_facts | `ar_facts.db` | 19.1 GB | 8 | Annual-report extraction store: document registry, ~33M extracted facts with quotes/units, processing provenance and FTS. Managed by the AR pipeline and hand-review overlays in equity_intelligence. |
| deck_figures | `deck_figures.db` | 9.9 GB | 14 | Investor-presentation/deck reader store: per-page vision-model calls, extracted printed numeric facts, chart trend labels and spend/queue ledgers, with symbol/ISIN/known_at resolvable via pages. |
| concall_facts | `concall_facts.db` | 741 MB | 4 | Concall transcript extraction store: one row per processed concall document, extracted guidance/analyst items as text, QA checks and FTS. |
| results_xbrl | `results_xbrl.db` | 6.1 GB | 4 | NSE quarterly-results XBRL store: filing registry, long facts and a pivoted quarterly view. Authoritative for reported quarterly financials; monetary values are in rupees. |
| bse_announcements | `bse_announcements.db` | 1.1 GB | 2 | BSE corporate-announcement feed: one metadata row per NEWSID (headline/category/timestamps/attachment) plus a per-scrip fetch ledger. Metadata only; the duckdb snapshot has a PIT-stamped copy. |

Top 60 tables (key tables first, then by row count; full lists in `schemas/`):

| table | rows | key columns | what it is | coverage |
|---|---|---|---|---|
| truth_duckdb.ar_facts | 32.4M | `doc_id`, `isin`, `symbol`, `fiscal_year` | One extracted annual-report fact per row: doc/piece/page, category/item, raw and numeric value, unit, period, basis, quote and model, with PIT known_at. | 2015-03-31..2026-03-31 |
| ar_facts.ar_facts | 32.4M | `doc_id`, `piece`, `isin`, `symbol`, `category` | One extracted annual-report fact per row: doc/piece/page, category/item, raw and numeric value, unit, period, basis, quote, model and check status. | 2015-03-31..2026-03-31 |
| results_xbrl.facts | 13.9M | `file`, `context`, `concept` | Long XBRL facts from NSE results filings: one row per file/context/concept with period, instant, value, unit and decimals. |  |
| deck_figures.facts | 13.6M | `sha256`, `page_no`, `metric` | One extracted numeric fact per row: deck sha256/page, prompt/model, line, metric, period, raw number, value, unit and final flag. |  |
| truth_duckdb.px_bse_adj | 6.8M | `date`, `sc_code`, `isin` | BSE daily rows with cumulative price/dividend factors and adjusted OHLC/volume plus total-return close. | 2019-01-01..2026-10-19 |
| truth_duckdb.px_nse_adj | 4.3M | `date`, `symbol`, `series` | NSE daily rows with cumulative price/dividend factors and adjusted OHLC/volume plus total-return close. | 2019-01-01..2026-10-19 |
| truth_duckdb.events | 3.3M | `isin`, `known_at_utc`, `kind`, `source_ref` | Unified company event timeline: one row per event across announcements, results, concalls, decks, ARs, shareholding, insider/SAST, deals, board meetings, PEAD posts and order alerts, with ISIN, known_at_utc, kind, source_ref and summary. | 2018-11-29T11:36:00..2026-10-19T18:29:59 |
| equity_intelligence.daily_price_delivery | 3.1M | `date`, `symbol`, `isin` | One row per symbol per trading day: normalized NSE/BSE OHLCV, turnover_lacs, delivery quantity/percent plus derived technical indicators (SMA/RSI/52-week high-low). | 2021-10-27..2026-09-24 |
| equity_intelligence.pib_releases | ~2.3M | `prid`, `doc_id` | PIB English press releases: one row per PRID with release/posting dates, ministry, title, full body, relevance flag and doc_id. |  |
| equity_intelligence.document_chunks | 2.3M | `chunk_id`, `doc_id`, `isin`, `symbol` | One row per chunk of a raw document: full text, embedding JSON, publication/event dates, symbol/isin and inferred fiscal period. |  |
| equity_intelligence.intelligence_fts | 2.3M | `rowid`, `chunk_id`, `symbol`, `isin` | FTS5 lexical index over document chunks: chunk_id, symbol/isin, source type, document date and document text. |  |
| bse_announcements.ann | 1.9M | `NEWSID`, `SCRIP_CD`, `symbol` | One BSE announcement per NEWSID: scrip code, headline/subject, category/subcategory, news/submission/dissemination timestamps, attachment name and derived symbol. | 2019-12-31..2026-10-19 |
| deck_figures.pages | 815.8k | `sha256`, `page_no`, `prompt_version` | One row per deck page per prompt version: doc/symbol/ISIN, doc_type, known_at, route, text/number counts, recall metrics, final model, fact count and status. | 2021-01-04T08:39:52.927..2026-09-29T22:49:57.223 |
| concall_facts.cc_items | 645.0k | `doc_id`, `list_name`, `idx`, `isin` | Extracted concall items: one row per doc_id/list_name/idx with metric, textual value, unit, period, basis, direction/firmness/signal, statement and quote. | 2016-05-20..2026-10-14T17:21:32.7 |
| equity_intelligence.corporate_documents | 127.2k | `id`, `isin`, `symbol`, `doc_type` | One row per corporate document metadata (annual report, concall, investor PPT, announcement, result): title, dates, URLs, local path, doc version and BSE/PIT timestamps. | 2015-01-13..2026-10-17 |
| truth_duckdb.results_filings | 106.6k | `file`, `isin`, `symbol` | One row per results XBRL filing: taxonomy, company/ISIN/symbol, period, consolidation/audit flags, dates, opinion, fact count, status, trading ISIN resolution and PIT known_at. | 2017-06-30..2026-09-30 |
| results_xbrl.filings | 106.6k | `file`, `isin`, `symbol` | One row per NSE results XBRL filing: taxonomy, company/ISIN/symbol, reporting period, consolidation/audit flags, dates, opinion, fact count and parse status. | 2017-06-30..2026-09-30 |
| truth_duckdb.cc_items | 87.9k | `doc_id`, `list_name`, `idx`, `isin` | Extracted concall items: one row per doc/list/index with metric, textual value, unit, period, basis, direction/firmness and quote, plus PIT known_at. | 2026-01-13T18:47:08.04..2026-10-14T17:21:32.7 |
| equity_intelligence.raw_documents | 34.8k | `doc_id` | One row per raw document ingested: title, source type, published date, fiscal period, URL/creator, hash and local path. | 2012-03-26..2026-10-16 |
| truth_duckdb.ar_docs | 33.7k | `doc_id`, `isin`, `symbol` | One row per annual report (doc_id) with ISIN/symbol/company, fiscal year and source, filed_at, sha256, page/piece counts, status and PIT known_at. | 2015-03-31..2026-09-07 |
| ar_facts.ar_docs | 33.7k | `doc_id`, `isin`, `symbol` | One row per annual-report PDF: ISIN/symbol/company, fiscal year and its source, filed_at, sha256, local path, page/piece counts and processing status. | 2015-03-31..2026-03-31 |
| truth_duckdb.pib_releases | 28.9k | `prid`, `doc_id` | Policy-relevant PIB releases: PRID, release/posting dates, ministry, title, relevance flag and doc_id (metadata only). | 2021-01-01..2026-10-19 |
| truth_duckdb.deck_sources | 26.4k | `source`, `source_id` | One row per deck source: symbol/ISIN, exchange code, known_at, title, URL, sha256, size and fetch status. | 2021-01-04T08:39:52.927..2026-09-29T22:49:57.223 |
| deck_figures.deck_sources | 26.4k | `source`, `source_id` | One row per deck source (BSE announcement etc.): symbol/ISIN, exchange code, known_at, title, URL, local path, sha256 and fetch status. | 2021-01-04T08:39:52.927..2026-09-29T22:49:57.223 |
| equity_intelligence.policy_events | ~21.8k | `id`, `source_kind`, `source_id` | One row per extracted policy event: source, title, policy name, instrument/stage, direction, sectors/companies/products, amount in Rs crore, effective/end dates and quote. |  |
| truth_duckdb.policy_events | 21.6k | `id`, `source_kind`, `source_id` | Extracted policy events: source, title, policy/instrument/stage, direction, sectors/companies/products, amount in Rs crore, effective dates, quote and PIT known_at. | 2019-01-31..2026-10-16T21:39 |
| equity_intelligence.quarterly_financials | 15.2k | `isin`, `symbol`, `quarter_end_date` | One row per ISIN/quarter end: revenue, EBITDA, PAT, margins, EPS and YoY/QoQ growth, in Rs crore. |  |
| equity_intelligence.annual_financials | 12.9k | `isin`, `symbol`, `fiscal_year` | One row per ISIN per fiscal year: revenue, EBITDA, net profit, EPS, margins, ROCE/ROE, debt, equity and cash-flow, all in Rs crore. |  |
| truth_duckdb.symbol_isin_history | 9.4k | `exchange`, `symbol`, `isin`, `first_date` | Symbol-to-ISIN mapping windows per exchange: first/last date and trading-day count. | 2019-01-01..2026-10-19 |
| equity_intelligence.symbol_isin_history | ~9.4k | `exchange`, `symbol`, `isin`, `first_date` | Symbol-to-ISIN mapping windows per exchange: first/last date and trading-day count. |  |
| concall_facts.cc_docs | 9.3k | `doc_id`, `isin`, `symbol` | One row per concall document processed: symbol/ISIN, filing time, status, model, token/cost stats, period discussed and check/raw JSON. | 2026-01-06T21:49:52.907..2026-10-14T17:21:32.7 |
| truth_duckdb.security_master | 8.4k | `isin` | ISIN-keyed security registry incl delisted names: issuer, NSE/BSE codes, BSE status, segment, listing/first/last trade and last-seen dates. |  |
| equity_intelligence.security_master | ~8.4k | `isin` | ISIN-keyed security registry including delisted names: issuer, NSE/BSE symbols and codes, BSE status, segment, listing/first/last trade and last-seen dates. |  |
| equity_intelligence.master_companies | ~6.8k | `isin`, `nse_symbol`, `bse_code` | Equity master: one row per ISIN with NSE symbol, BSE code, name, industry/sector, market-cap tier, index flags, active and screenable flags. |  |
| truth_duckdb.nse_master | 3.2k | `symbol`, `isin` | NSE symbol master: one row per symbol with ISIN, name and segment. | 20MICRONS..ZYDUSWELL |
| truth_duckdb.fii_dii_cash | 1.9k | `date` | Daily FII/DII cash flows in Rs crore plus Nifty close/change, with PIT known_at. | 2019-01-01..2026-10-19 |
| truth_duckdb.cc_docs | 1.2k | `doc_id`, `isin`, `symbol` | One row per concall document: doc_id, ISIN/symbol, filing time, processing status/model, token stats, period discussed and PIT known_at. | 2026-01-06T21:49:52.907..2026-10-14T17:21:32.7 |
| equity_intelligence.shareholding | 40 | `symbol`, `isin`, `quarter_end`, `record_id` | One row per shareholding filing (record_id): promoter/pledged/encumbered, FII, DII, MF, insurance, retail and FPI-limit percentages already multiplied by 100. |  |
| ar_facts.ar_facts_fts | ~33.0M | `rowid` | FTS5 full-text index over ar_facts item/category. |  |
| deck_figures.facts_metric_fts | ~15.1M | `rowid` | FTS5 full-text index over facts.metric. |  |
| truth_duckdb.results_facts | 13.9M | `file`, `concept`, `context` | Long XBRL facts from results filings: file/context/concept with period start/end/instant, value, unit, decimals and period_kind. | 2017-06-30..2026-09-30 |
| truth_duckdb.deck_facts | 13.6M | `isin`, `symbol`, `sha256`, `page_no`, `metric` | One extracted numeric deck fact per row: ISIN/symbol/doc_type from the page, sha256/page, model, metric, period, raw number, value, unit and final flag, plus PIT known_at. | 2021-01-04T03:09:52.927000..2026-09-29T17:19:57.223000 |
| equity_intelligence.mkt_bse_eq_daily | ~7.5M | `date`, `sc_code`, `isin` | BSE bhavcopy: one row per scrip per date with OHLC, previous close, volume, turnover_inr, trades, group and type. |  |
| equity_intelligence.mkt_bse_delivery_daily | ~7.5M | `date`, `sc_code` | BSE gross delivery: one row per scrip per date with deliverable quantity/value, volume, turnover and delivery percent. |  |
| truth_duckdb.px_daily | 7.3M | `entity_id`, `date` | Primary daily price series: one row per issuer entity per date, NSE row when it traded that day else BSE, with raw and adjusted OHLC/volume plus total-return close. |  |
| truth_duckdb.px_primary_raw | 7.3M | `entity_id`, `date` | Internal one-row-per-entity/day close/open used to compute corporate-action factors: NSE preferred, else BSE, with exchange and previous close/date. |  |
| truth_duckdb.px_bse | 6.8M | `date`, `sc_code`, `isin` | Unified BSE equity daily rows: date, sc_code, ISIN/symbol/name/group, OHLC, volume, value_inr, trades and delivery, plus entity_id. | 2019-01-01..2026-10-19 |
| deck_figures.facts_unit_fix | ~6.4M | `fact_rowid` | Audit of unit corrections: fact_rowid, old/new unit and how it was changed. |  |
| equity_intelligence.mkt_nse_full_daily | ~4.5M | `date`, `symbol`, `series` | NSE sec_bhavdata_full: one row per date/symbol/series with OHLC, volume, turnover_lacs and delivery quantity/percent. |  |
| truth_duckdb.px_nse | 4.3M | `date`, `symbol`, `series` | Unified NSE equity daily rows: date, symbol/series/ISIN, OHLC, volume, value_inr, trades and delivery, plus entity_id. | 2019-01-01..2026-10-19 |
| truth_duckdb.price_bands | 4.0M | `date`, `symbol`, `series` | Daily price band per symbol/series: 2/5/10/20/40 percent or No Band, with remarks and PIT known_at. |  |
| equity_intelligence.pib_releases_fts | ~2.3M | `rowid` | FTS5 full-text index over pib_releases (title, body, ministry). |  |
| equity_intelligence.pib_ml_releases | ~2.3M | `prid`, `doc_id` | PIB regional-language releases: one row per PRID with language, ministry, title, full body, linked English PRID and translation metadata. |  |
| equity_intelligence.pib_ml_releases_fts | ~2.3M | `rowid` | FTS5 full-text index over pib_ml_releases (title, body, ministry). |  |
| truth_duckdb.bse_ann | 1.9M | `NEWSID`, `SCRIP_CD`, `symbol` | BSE announcements: one row per NEWSID with scrip code, headline/subject, category, timestamps, attachment and derived symbol, plus PIT known_at. | 2019-12-31T20:59:43.797..2026-10-19T14:10:50.513 |
| equity_intelligence.mkt_nse_eq_daily | ~1.4M | `date`, `symbol`, `series` | NSE old-format bhavcopy (2019-01 to 2021-10): one row per date/symbol/series with OHLC, turnover_inr and delivery. |  |
| equity_intelligence.price_bands | ~1.1M | `date`, `symbol`, `series` | One row per symbol/series/date: price band (2/5/10/20/40 percent or No Band) and remarks. |  |
| deck_figures.outputs | ~822.2k | `sha256`, `page_no`, `prompt_version`, `model` | One row per vision-model page output: sha256/page/prompt/model, settings, timing, tokens, USD cost and raw output. |  |
| truth_duckdb.deck_pages | 815.8k | `sha256`, `page_no`, `prompt_version` | One row per deck page per prompt: doc/symbol/ISIN, doc_type, route, fact count, status and PIT known_at. |  |
| concall_facts.cc_items_fts | ~717.8k | `rowid` | FTS5 full-text index over concall items (metric, statement, quote). |  |

Row counts are the 2026-10-24 catalog measurements (exact for the large tables, `~` = sqlite_stat1/MAX(rowid) estimate). **Never run `COUNT(*)` on `equity_intelligence.db`**; use the cache or `sqlite_stat1`.

## 3. How to query

Open SQLite read-only; never a bare `sqlite3.connect`:

```python
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro
DATA = Path(os.environ["REALITY_DATA_ROOT"])  # or repo/reality_engine/data
con = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)  # mode=ro + query_only
```

The `reality-data` MCP tools (prefer them over ad-hoc SQL):

| tool | use it when |
|---|---|
| `catalog` | first call: DB/table/row/coverage map (already summarized here). |
| `resolve` | symbol/name/ISIN -> canonical identity and ISIN history. |
| `price` | OHLCV, delivery %, traded value, adjustment factors for one range. |
| `facts` | annual-report / XBRL / deck / concall / guidance facts for a company. |
| `search_docs` | hybrid vector+FTS text search over concalls, decks, ARs, announcements. |
| `sql` | bounded read-only SELECT/WITH when the typed tools do not fit. |

Rules that prevent wrong answers:
- `document_chunks` is 2.9M rows: never correlated subqueries or unindexed `GROUP BY` on it.
- `corporate_documents.doc_date` is the **crawl date**, never a filing date; use
  `publication_date` / `bse_dissem_ts` / `call_date` for PIT work.
- Point-in-time: anything used for research carries `known_at` (or `known_at_utc`);
  never use data that was not known at the decision time.
- Trust layer (AGENTS.md §3.13): exclude `substrate_quarantine` keys and `*_demo` /
  `seed_*_demo` tables before showing substrate rows to a model; report degradation
  counts alongside the answer.
- One writer per SQLite DB; read-only connections only unless the task says write.

## 4. Tests

Exact commands (run the narrow module first; the whole-repo discovery is slow):

```bash
python -m unittest discover -s reality_engine/tests -p "test_*.py"
python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_dsh_worker_stress
claude plugin validate <abs mod dir>
claude plugin test --file <abs test file> <abs mod dir>
```

Data-touching tests must use in-memory/temp fixtures, never the live DBs.

| module | its test file |
|---|---|
| `reality_engine.agent.orchestrator` | test_agent_and_reporting.py, test_portfolio_ledger.py, test_screener_substrate_routing.py |
| `reality_engine.agent.schemas` | test_distillation_macro.py |
| `reality_engine.cli` | test_horizon_excess.py, test_macro_ingest.py, test_macro_pdf_fetcher.py |
| `reality_engine.config` | test_agent_and_reporting.py, test_bootstrap.py, test_news_retention.py, test_raw_root.py, test_v2_ingestion_adapters.py |
| `reality_engine.db.database` | test_action_thesis.py, test_attention_ranker.py, test_backfill_call_rows.py, test_bootstrap.py, test_bse_backfill.py, test_bse_fundamentals_client.py, test_catchup_scheduler.py, test_continuous_loop.py, test_deals_client.py, test_derived_substrate.py, test_desk_backtest.py, test_distillation_macro.py, test_distilled_expansion.py, test_document_industry_tag.py, test_document_pit.py, test_ensemble_ranker.py, test_ensemble_weighted.py, test_eod_corrector.py, test_event_graph.py, test_factor_loaders.py, test_factor_spine.py, test_financial_denominator.py, test_fiscal_extraction.py, test_forecast_capacity.py, test_horizon_excess.py, test_index_backfill.py, test_insider_trades.py, test_intel_search.py, test_lifecycle_pruning.py, test_macro_ingest.py, test_macro_pdf_fetcher.py, test_market_gap_backfill.py, test_master_bse_admission.py, test_master_upsert.py, test_moat_backfill.py, test_moe_all_universe.py, test_move_attribution.py, test_news_announcements.py, test_news_explainer.py, test_news_feed_client.py, test_news_retention.py, test_news_vision.py, test_nightly_alpha.py, test_peer_graph_and_hygiene.py, test_perf_guards.py, test_policy_coverage.py, test_policy_eni.py, test_policy_press_client.py, test_portfolio_ledger.py, test_pua_fallback.py, test_repo_identity.py, test_repo_lane.py, test_rumor_backfill.py, test_rumor_scorer.py, test_screener_substrate_routing.py, test_sip_backtest.py, test_sip_signals.py, test_skill_loop.py, test_supply_chain.py, test_telegram_hardening.py, test_v2_ingestion_adapters.py |
| `reality_engine.db.fixtures` | test_bootstrap.py |
| `reality_engine.db.readonly` | test_missing_series_fetchers.py, test_readonly.py |
| `reality_engine.db.repository` | test_action_thesis.py, test_attention_ranker.py, test_backfill_call_rows.py, test_bootstrap.py, test_deals_client.py, test_derived_substrate.py, test_distillation_macro.py, test_distilled_expansion.py, test_document_industry_tag.py, test_document_pit.py, test_ensemble_ranker.py, test_ensemble_weighted.py, test_eod_corrector.py, test_factor_spine.py, test_financial_denominator.py, test_forecast_capacity.py, test_index_backfill.py, test_insider_trades.py, test_intel_search.py, test_macro_ingest.py, test_macro_pdf_fetcher.py, test_market_gap_backfill.py, test_master_bse_admission.py, test_master_upsert.py, test_moat_backfill.py, test_moe_all_universe.py, test_move_attribution.py, test_news_announcements.py, test_news_explainer.py, test_news_feed_client.py, test_news_vision.py, test_peer_graph_and_hygiene.py, test_policy_coverage.py, test_policy_eni.py, test_policy_press_client.py, test_portfolio_ledger.py, test_quant_hardening.py, test_repo_identity.py, test_repo_lane.py, test_rumor_scorer.py, test_screener_substrate_routing.py, test_sip_signals.py, test_supply_chain.py, test_telegram_hardening.py, test_v2_ingestion_adapters.py |
| `reality_engine.db.vector_store` | test_perf_guards.py |
| `reality_engine.harness.adapter` | test_harness_h01.py |
| `reality_engine.harness.benchmark` | test_harness_h01.py, test_harness_h01_wall.py |
| `reality_engine.harness.book` | test_harness_h01.py, test_harness_h01_wall.py |
| `reality_engine.harness.costs_tax` | test_harness_h01.py |
| `reality_engine.harness.coverage` | test_harness_h01.py |
| `reality_engine.harness.data` | test_harness_h01.py, test_harness_h01_wall.py |
| `reality_engine.harness.execution` | test_harness_h01.py |
| `reality_engine.harness.run_h01` | test_harness_h01.py |
| `reality_engine.harness.run_h01_selection` | test_harness_h01_selection.py |
| `reality_engine.harness.run_h01_wall` | test_harness_h01_wall.py |
| `reality_engine.harness.stats` | test_harness_h01.py, test_harness_h02.py |
| `reality_engine.harness.universe` | test_harness_h01.py |
| `reality_engine.ingestion.bse_fundamentals_client` | test_bse_fundamentals_client.py |
| `reality_engine.ingestion.deals_client` | test_deals_client.py, test_market_gap_backfill.py |
| `reality_engine.ingestion.headless_fetcher` | test_filing_ingestion.py |
| `reality_engine.ingestion.llm_lens_client` | test_llm_lens_client.py |
| `reality_engine.ingestion.macro_pdf_fetcher` | test_macro_pdf_fetcher.py |
| `reality_engine.ingestion.master_sync` | test_master_bse_admission.py |
| `reality_engine.ingestion.news_announcements_client` | test_news_announcements.py |
| `reality_engine.ingestion.news_feed_client` | test_news_feed_client.py |
| `reality_engine.ingestion.onnx_embedder` | test_onnx_embedder.py, test_shared_engines.py |
| `reality_engine.ingestion.pdf_ingestor` | test_document_industry_tag.py, test_fiscal_extraction.py, test_macro_ingest.py, test_pua_fallback.py, test_repo_identity.py |
| `reality_engine.ingestion.policy_press_client` | test_policy_press_client.py |
| `reality_engine.ingestion.telegram_client` | test_telegram_hardening.py |
| `reality_engine.pilot.build_t1` | test_pilot_t1.py |
| `reality_engine.pilot.macro_claims` | test_macro_claim_target.py |
| `reality_engine.pipeline.bootstrap` | test_bootstrap.py |
| `reality_engine.pipeline.bse_backfill` | test_bse_backfill.py |
| `reality_engine.pipeline.capacity_loop` | test_forecast_capacity.py |
| `reality_engine.pipeline.catchup_scheduler` | test_catchup_scheduler.py |
| `reality_engine.pipeline.continuous_loop` | test_continuous_loop.py |
| `reality_engine.pipeline.data_audit` | test_data_audit_holiday.py, test_repo_lane.py |
| `reality_engine.pipeline.forecast_tester` | test_forecast_capacity.py |
| `reality_engine.pipeline.news_loop` | test_news_loop.py |
| `reality_engine.pipeline.nightly_alpha` | test_nightly_alpha.py |
| `reality_engine.pipeline.offer_backfill` | test_offer_backfill.py |
| `reality_engine.pipeline.panic_monitor` | test_quant_hardening.py |
| `reality_engine.pipeline.routines` | test_routines.py |
| `reality_engine.processing.ar_row_guards` | test_ar_row_guards.py |
| `reality_engine.processing.business_profiler` | test_derived_substrate.py, test_moat_backfill.py |
| `reality_engine.processing.capacity_governor` | test_forecast_capacity.py |
| `reality_engine.processing.causal_engine` | test_supply_chain.py |
| `reality_engine.processing.chunker_v2` | test_chunker_v2.py, test_chunker_v3.py |
| `reality_engine.processing.chunker_v3` | test_chunker_v3.py |
| `reality_engine.processing.composite_screener` | test_action_thesis.py, test_ensemble_ranker.py, test_policy_coverage.py, test_quant_hardening.py |
| `reality_engine.processing.desk_backtest` | test_desk_backtest.py |
| `reality_engine.processing.distillation_engine` | test_distillation_macro.py, test_distilled_expansion.py |
| `reality_engine.processing.ensemble_ranker` | test_action_thesis.py, test_eod_corrector.py, test_move_attribution.py |
| `reality_engine.processing.eod_corrector` | test_eod_corrector.py, test_move_attribution.py |
| `reality_engine.processing.event_graph` | test_eod_corrector.py, test_event_graph.py |
| `reality_engine.processing.factor_loaders` | test_factor_loaders.py, test_missing_series_fetchers.py |
| `reality_engine.processing.factor_spine` | test_factor_spine.py |
| `reality_engine.processing.financial_validator` | test_financial_denominator.py |
| `reality_engine.processing.fundamental_engine` | test_quant_hardening.py |
| `reality_engine.processing.instrument_classifier` | test_financial_denominator.py |
| `reality_engine.processing.moat_scorer` | test_derived_substrate.py |
| `reality_engine.processing.move_attributor` | test_backfill_call_rows.py |
| `reality_engine.processing.news_explainer` | test_news_explainer.py, test_news_extractor.py |
| `reality_engine.processing.news_extractor` | test_news_extractor.py |
| `reality_engine.processing.news_vision` | test_news_vision.py |
| `reality_engine.processing.peer_graph` | test_peer_graph_and_hygiene.py |
| `reality_engine.processing.policy_engine` | test_derived_substrate.py, test_policy_coverage.py, test_policy_eni.py |
| `reality_engine.processing.portfolio_ledger` | test_desk_backtest.py, test_horizon_excess.py, test_portfolio_ledger.py |
| `reality_engine.processing.pruning_engine` | test_factor_spine.py, test_macro_ingest.py |
| `reality_engine.processing.rumor_backfill` | test_rumor_backfill.py |
| `reality_engine.processing.rumor_scorer` | test_rumor_scorer.py |
| `reality_engine.processing.sip_backtest` | test_desk_backtest.py, test_sip_backtest.py |
| `reality_engine.processing.sip_signals` | test_sip_signals.py |
| `reality_engine.processing.skill_loop` | test_portfolio_ledger.py, test_skill_loop.py |
| `reality_engine.processing.substrate_hygiene` | test_desk_backtest.py, test_horizon_excess.py, test_peer_graph_and_hygiene.py, test_portfolio_ledger.py |
| `reality_engine.processing.video_screen_ocr` | test_video_ocr_pilot.py |
| `reality_engine.query.answer` | test_query_planners.py, test_query_v1.py |
| `reality_engine.query.compute` | test_query_compute.py |
| `reality_engine.query.ctx` | test_macro_claim_target.py, test_query_planners.py, test_query_v1.py |
| `reality_engine.query.decompose` | test_query_v1.py |
| `reality_engine.query.planners.ripple` | test_macro_claim_target.py |
| `reality_engine.query.rerank` | test_query_v1.py |
| `reality_engine.query.router` | test_query_router.py, test_query_v1.py |
| `reality_engine.raw_store` | test_dedupe_raw.py |
| `reality_engine.reporting.writer` | test_action_thesis.py, test_agent_and_reporting.py |
| `reality_engine.scripts.backfill_call_rows` | test_backfill_call_rows.py |
| `reality_engine.scripts.backfill_fiscal_periods` | test_fiscal_extraction.py |
| `reality_engine.scripts.backfill_index_ohlc` | test_index_backfill.py |
| `reality_engine.scripts.backfill_raw_document_symbols` | test_raw_document_symbols.py |
| `reality_engine.scripts.build_bulk_block_deals` | test_market_gap_backfill.py |
| `reality_engine.scripts.build_deck_page_text` | test_new_feeds_g2.py |
| `reality_engine.scripts.build_etf_premium` | test_new_feeds_g2.py |
| `reality_engine.scripts.build_insider_trades` | test_insider_trades.py |
| `reality_engine.scripts.build_universe_membership` | test_universe_builder.py |
| `reality_engine.scripts.clean_insider_dates` | test_market_gap_backfill.py |
| `reality_engine.scripts.concall_refetch` | test_concall_refetch.py |
| `reality_engine.scripts.dedupe_raw` | test_dedupe_raw.py |
| `reality_engine.scripts.dsh_heartbeat` | test_dsh_worker_plugin.py |
| `reality_engine.scripts.embed_prototype_compare` | test_embed_prototype.py |
| `reality_engine.scripts.extract_deck_figures` | test_extract_deck_figures.py |
| `reality_engine.scripts.fetch_commodity_series` | test_missing_series_fetchers.py |
| `reality_engine.scripts.fetch_eq_bhavcopy_gaps` | test_missing_series_fetchers.py |
| `reality_engine.scripts.fetch_etf_nav` | test_fetch_etf_nav_timeout.py |
| `reality_engine.scripts.fetch_fo_bhavcopy` | test_missing_series_fetchers.py |
| `reality_engine.scripts.fetch_index_history` | test_pilot_t1.py |
| `reality_engine.scripts.fetch_market_raw` | test_market_gap_backfill.py |
| `reality_engine.scripts.fetch_nse_api_raw` | test_market_gap_backfill.py |
| `reality_engine.scripts.fetch_originals` | test_fetch_originals.py |
| `reality_engine.scripts.fetch_price_bands` | test_pilot_t1.py |
| `reality_engine.scripts.fetch_results_notes_text` | test_new_feeds_g2.py |
| `reality_engine.scripts.load_deck_chunks` | test_deck_chunk_load.py |
| `reality_engine.scripts.load_market_raw` | test_market_gap_backfill.py |
| `reality_engine.scripts.market_session_coverage` | test_market_gap_backfill.py |
| `reality_engine.scripts.merge_lane_db` | test_merge_lane_db.py |
| `reality_engine.scripts.migrate_raw_to_d` | test_raw_root.py |
| `reality_engine.scripts.resource_watchdog` | test_resource_watchdog.py |
| `reality_engine.scripts.run_deepseek_harness` | test_deepseek_harness_controls.py, test_dsh_heartbeat.py |
| `reality_engine.scripts.seed_track_record` | test_portfolio_ledger.py |
| `reality_engine.search.intel_search` | test_intel_search.py, test_rumor_backfill.py |
| `reality_engine.toolbelt.cost_ledger` | test_toolbelt.py |
| `reality_engine.toolbelt.coverage_peek` | test_coverage_peek.py |
| `reality_engine.toolbelt.drive_fetch` | test_deck_chunk_load.py, test_toolbelt.py |
| `reality_engine.toolbelt.find_docs` | test_toolbelt.py |
| `reality_engine.toolbelt.job_peek` | test_toolbelt.py |
| `reality_engine.toolbelt.mod_test` | test_toolbelt.py |
| `reality_engine.toolbelt.render_pages` | test_toolbelt.py |
| `reality_engine.toolbelt.sample_rows` | test_toolbelt.py |
| `reality_engine.ui.dashboard` | test_cli_and_dashboard.py |

## 5. Sandbox limits + workarounds

Digest only; full rules in `tasks/worker_context/SANDBOX.md` (read it before installing, writing outside the workspace, committing or launching).

| `permission` | dsh mode / approval | effect |
|---|---|---|
| `read-only` | `read-only`, `ask` | no writes; confined pwsh gets no temp dir, so `tempfile.mkdtemp()` fails |
| `workspace-write` | `workspace-write`, `ask` | writes under the session cwd plus a private per-session temp |
| `danger-full-access` | `danger-full-access`, `never` | unconfined |

- Writable root = session cwd only; there is no extra-writable-roots setting, and a junction to `REALITY_DATA_ROOT` does not help (the resolved target is checked).
- Temp/caches: `.tmp/` (`TMP`/`TEMP`, pip/uv/npm caches). Never `%LOCALAPPDATA%\Temp`. `pip install --target .tmp/x ...`; optional `.venv-<task>`.
- `write_scope='data'`: needs `confirm_data_write=true` + `writes=[...]` + `approved_by`; runs `danger-full-access` exactly like `full` (`confirm_full_access=true`) — policy, not enforcement. A mutating main-checkout worker needs `confirm_repo_root_write=true`.
- Commit: write `.tmp/commit.request.json` `{"message": ...}` -> `.tmp/commit.result.json`; direct `git commit` is denied.
- Detached launch (data/full only): write `.tmp/launch.request.json` (`cmd`, `log`, `cwd`, `env`) -> `.tmp/launch.result.json`.
- Nested-sandbox demos cannot run from a confined token; see `tasks/worker_context/sandbox_probe.py`.

## 6. Conventions

- Storage (AGENTS.md §3.2): local files only. SQLite in WAL mode holds the live data
  (`equity_intelligence.db`, `ar_facts.db`, `deck_figures.db`, `concall_facts.db`,
  `results_xbrl.db`, `bse_announcements.db`); the dated DuckDB snapshot is read-only and
  used for PIT research/backtests. PostgreSQL/pgvector is not installed and not used.
- Delivered (normalized) facts are the decision substrate; `raw_documents` is
  audit/replay only. Query via `connect_ro` or the `reality-data` tools; keep statements
  bounded.
- Trust layer (§3.13): exclude `substrate_quarantine` keys and demo/seed tables before
  presenting substrate rows; state degradation counts next to the answer.
- Point-in-time `known_at` for every research input; newest -> oldest for backfills.
- One writer per SQLite DB. Additive schema changes only. No `git stash` in worktrees.
- Match surrounding style; no unrequested abstractions.
- Paid API calls need an explicit budget in the brief. Keys come from
  `reality_engine.scripts.resource_watchdog.user_env()`; never print key values.
- Free models only on subscriptions; Go key 1 is dead, Go key 2 + Kilo keys 1/2
  work, and every Go call sends a stable session id.

## 7. Recent decisions

Last 30 one-line entries from `reality_engine/data/hotline/decisions.md`:

- **The nightly DB backup window is 05:00–13:00 IST** (2026-10-19 01:32 IST): Shivam allowed database uploads "after 5 am and till 1 pm IST everyday" -> rule: the job stages and uploads only inside that window -> why: it shares the uplink w …
- **The EOD job retries the last 3 days instead of marking a premature run permanently "missing"** (2026-10-19 01:04 IST, 4f3f1955): a run before the exchange published marked that day `missing` and it was never fetched -> fix: days from th …
- **iNAV is struck on the underlying's same-day session (index lag 0, FX lag 0)** (2026-10-19 05:23 IST, 52dd704a): alignment tests gave a median daily absolute difference of 0.159% at lag 0/0, against 1.003% at lag 1/0 and 1.047% at lag 1/ …
- **BSE total-return indices are derived from the price index plus published dividend yield, scaled by 0.8** (2026-10-19 04:56 IST, 4d4ea946): BSE's own archive has price indices only, Asia Index's TRI page is JavaScript-rendered, and the o …
- **The unified events table is the timing source across stores** (2026-10-19 05:50 IST, 487f2ee6): events were split across announcements, insider, SAST, deals and other tables -> fix: one events table with 2,781,137 rows (2,712,099 with I …
- **The industry map reads `basicIndustry`/`industryInfo`, not `industry`** (2026-10-19 05:25 IST, e99eeef3): the old map was unusable (1,868 companies "General Diversified", 1,751 "Other", 2,714 blank), BSE's masters had zero industry valu …
- **`state(isin, t)` is the point-in-time access path, and it was hand-checked** (2026-10-19 05:24 IST, 3a9427a0): 300 calls gave latency p50 0.080 s, p95 0.156 s and max 0.224 s; 53 hand checks against raw sources produced 53 OK and 0 mism …
- **Tax rules are built from the enacted Gazette texts, with every quote verified against its PDF** (2026-10-19 04:40 IST, 89de38ef): the Budget speech is not the enacted law, and the first downloaded PDF was the Bill as introduced -> fix: …
- **The query indexes are kept in sync by triggers, and the vector store was made append-safe** (2026-10-19 04:32 IST, df0cf103): deck KPI for one company was 10.6 s, market-wide deck search 12.7 s, NSE price history 0.29 s, market-wide qua …
- **The DuckDB snapshot carries UTC point-in-time columns and is capped at 4 GB of memory** (2026-10-19 04:32 IST, 2d63adfd): SQLite could not scan tens of millions of rows fast enough, and the snapshot build spiked memory -> fix: a dated D …
- **XBRL values are pivoted by context (`OneD`/`FourD`), not by the stored period dates** (2026-10-19 04:08 IST): some files carry both consolidated and standalone facts, and using the stored period produced duplicate or wrong values -> fix …
- **Point-in-time columns are stored in UTC, converted from IST at build time** (2026-10-19 04:05 IST, 2d63adfd): sources mixed date-only and minute stamps, with PIB's stamp "IST, minute precision" and BSE times as naive IST strings -> fix: …
- **Results are joined through `filings_isin`, not the ISIN written inside the XBRL** (2026-10-19 03:31 IST, df0cf103): `results_xbrl.filings.isin` carried stale pre-split or mistyped ISINs for 11,682 of 76,416 filings (about 15%), so they …
- **The universe comes from `security_master`/`symbol_isin_history`, not `master_companies`** (2026-10-19 02:00 IST): 3,923 of 8,736 BSE-priced ISINs were not in `master_companies` (delisted, SME, BSE-only), and 615 NSE symbols trading in 2 …
- **No analyst consensus estimates: expectations are the company's own guidance and trend** (2026-10-19 01:45 IST): consensus data is paid and was not acquired -> design choice: backtests compute expectations from the company's own guidance …
- **Known data holes are recorded rather than papered over** (2026-10-19 01:20 IST): the audit listed no total-return indices (benchmark understated by roughly 1–1.5% a year), one index-membership snapshot (30 Sep 2026, 3 indices), no share …
- **The EOD price job runs weekdays at 19:35 IST** (2026-10-19 01:04 IST, 4f3f1955): prices had stopped at 9 Oct because no scheduled EOD job existed and the one-off 6 Oct backfill ran through 9 Oct -> fix: `RealityEngine-EODMarket` fetches …
- **Quarterly results use a rule-based XBRL parser, no LLM and no embeddings** (2026-10-19 00:52 IST, 35ca5bea): XBRL carries concept, period, unit and context, so the parser writes one row per filing with exchange dissemination time and on …
- **`known_at` is the exchange or publication time, never the crawl date** (2026-10-19 00:38 IST): the crawl date had leaked into the search layer for about 10k documents -> fix: the search layer was repaired and the rule is `known_at` = ex …
- **Big Orders cards are OCR'd, with name and symbol matched and the name trusted on disagreement** (2026-10-18 23:09 IST, ae81a9d8 and c9b6b640): OCR occasionally misread a symbol (OBSCP as "OBSCPL") -> fix: match both the company-name lin …
- **`search_docs_date_mismatch` watches every search-index document** (2026-10-18 20:50 IST, 0700b368): after the transcript repair the check found 0 transcript mismatches but 3,496 of 3,520 annual reports and about 936 of 988 investor pres …
- **Crawl dates were written into 5,725 transcripts and about 127k chunks** (2026-10-18 20:43 IST, 29c446a7): `--local-only` passed `doc_date`, which is the crawl date, so chunks were stamped 2026-10-18 instead of the call date -> fix: sele …
- **The hotline is the shared-context protocol, with `.dsh/AGENTS.md` for DeepSeek** (2026-10-20 03:13 IST): after Shivam's challenge that a worker cannot know what happened in the chat, the session wrote `hotline/README.md`, `hotline/hotli …
- **The generated hotline directory is git-ignored** (2026-10-20 03:12 IST): both generators write into `reality_engine/data/hotline/generated/`, and that path was added to `.gitignore` -> why: it is regenerated content, not source -> commi …
- **A whole session is digested into a readable worker context** (2026-10-20 03:08 IST): the Claude Code transcript was 6.20 MB at `~/.claude/projects/.../10203977-....jsonl`; `session_digest.py` turned it into a 229 KB (about 59k tokens) d …
- **Every digest is secret-scanned by value before a worker reads it** (2026-10-20 03:08 IST): a naive scan flagged 30 lines, all false alarms (`task-notification` tags) -> the real check tested whether any of 50 secret environment values a …
- **`worker_context.py` writes a fresh live-state file before every worker task** (2026-10-20 03:05 IST, 099f7224): a worker had answered from incomplete facts and was blamed for it -> the script writes `data/dsh_tasks/context_now.md` with …
- **When a worker answer is wrong, first ask what it could not see** (2026-10-20 03:04 IST): the first Drive-status answer was blamed on the model, but the live facts it needed were not in its task -> rule: on a wrong worker answer, fix the …
- **Beam transcript reader BENCHED** (2026-10-20 ~19:55 IST, Shivam via the laptop session): beam-free got an upstream HTTP 429 on every call from 11:52 and wrote ~32 docs/hour as permanent `error` -> stopped the reader (shards 1,2,3/4), re …
- **Beam: revised to 6 workers + 15-min single tap** (2026-10-20 20:05 IST, Shivam, replaces the bench above): probe 20:02 = HTTP 429 on both keys. Reader restarted with --workers 6 (was 32; ramp by bisection while 429s stay ~0), 256 queued …

Last two `## ` sections of `tasks/STATE.md` (truncated):

### Hand-off 2026-10-24 evening (laptop session ae59bca5)

Done today (all committed on main, nothing pushed after 2f7f71b):
- Market data refreshed to 2026-10-23: exchange prices/delivery, FII/DII (xlrd installed for NSE fii_stats), NSDL FPI, bulk/block/short deals, NSE PIT + SAST, BSE announcements, PIB; `daily_price_delivery` now to 2026-10-23.
- `insider_trades_v2`: 333,712 trades (NSE legacy 2019-01..2026-05-02, NSE PIT XBRL 2026-05-03.., BSE 2019-22 with no known_at); 67 implausible dates nulled + flagged. Legacy `insider_trades` left empty; `repository.get_recent_insider_trades` reads v2.
- FY26 annual reports: all 5,362 PDFs on disk (Drive restore to data/pdfs + D:\RealityEngine\pdfs, rest from BSE); 5,361 chunked (SDC hangs PyMuPDF); `document_chunks` 2,939,096; FY26 corpus 908,969 chunks; 70 reports have garbled font layers (quality follow-up). `raw_documents` now has symbol/isin/symbol_source (all 8,268 AR docs filled).
- AR embedding decision PENDING (Shivam): FY26 chunks ~$20 on DeepInfra Nemotron-8B vs ~$5.6 NVFP4 (+ Nemotron-3.5-Rerank-8B, ~$0.0007/search). Pilot: tasks via scripts/embed_ar_test.py + embed_ar_rerank_test.py (test spend $0.216 of $0.25). Free NVIDIA/OpenRouter 3.5-8B endpoints timed out all afternoon.
- reality-data MCP drop: root cause = server only in project .mcp.json (dsh-worker also in user scope survived a config reload). Fixed: added to user scope (`claude mcp add-json -s user`), allowlisted, warm-up moved off the handshake, lifecycle log in plugins/reality-data/server/.cache/lifecycle.log. dsh profiles: reality-data reconnect maxAttempts 40.
- `reality_engine/db/readonly.connect_ro` (timeout + temp_store=MEMORY) used by reality-data; AGENTS.md updated (live storage, query rule, subagent 15-min interrupt rule).
- Resource watchdog: laptop profile = monitor-only (no job auto-starts; paid/GPU/PC-only refuse), Startup entry installed, running. Start it only via WMI (`Invoke-CimMethod Win32_Process Create`) — processes started from Claude's shell die with its tree.
- Subagents already enabled by dsh-base (maxDepth 1, max 8 active); no per-child time cap exists in dsh 0.2.1.

Open:
1. DeepSeek workers pane mod v2 (plugins/dsh-workers-pane, live copy in ~/.claude/dev-mods/<session>/dsh-wo
… (truncated; read tasks/STATE.md)

### START HERE — next session (written 2026-10-25 ~00:45 IST, session ae59bca5)

**First: worker optimisations — launch sheet + per-worker briefs in `tasks/optimizations/` (README.md, 00_SHARED_CONTEXT.md, 01–04)** (Shivam: DeepSeek workers too slow — 90–270 tool calls / 30–50 min per task, mostly
orientation + sandbox friction). Build, in this order (dsh-worker items after a restart has loaded progress reports):
1. Worker context pack (repo map, live schemas/row counts, which DB/tool for what, `connect_ro`, test commands,
   sandbox limits + workarounds, conventions: known_at PIT, free models only, newest-first), regenerated nightly,
   auto-attached by `start_worker`.
2. Brief template with a definition of done (goal → files → acceptance checks → test command → report format).
3. Toolbelt scripts: PDF→PNG, Drive fetch by sha, table sampler, per-file mod tests, paid-call cost ledger.
4. Sandbox fixes: pre-installed deps, permitted temp dir (tempfile DACL issue), data-writer mode for approved DB jobs,
   worktree commit permission (OCR worker's commit was blocked); metric "tool calls before first edit".
5. LSP: pyright + Claude Code Python LSP plugin; an LSP MCP server (definition/references/symbols) for DeepSeek workers.
   (3 and 5 independent; 1, 2, 4 touch plugins/dsh-worker.)

**Just landed (on main, not pushed):** dsh-worker progress digests every 20 min (`progress.jsonl`/`progress.md`,
`worker_progress` tool, safe status-ping prefix) — merged `6c0f59e`, 73 tests pass; needs an app restart to load.
DeepSeek-workers pane v3 is a user-level plugin (`dsh-workers@reality-engine`, reads plugins/dsh-workers-pane).

**Paused work — read the hand-offs in `tasks/handoff/`, code is on branches (NOT merged, needs review):**
- Concall runner patch + pilot → branch `wip/concall-runner-2026-10-24` (`dfdeb7a`), `CONCALL_RUNNER_2026-10-24.md`.
  Pilot 25/25 done. Open: output truncation (output caps), chunk text lowercased/no line breaks breaks speaker
  detection, date resolver. Free readers left: beam-free on Go key 2 + Kilo keys 1/2 (Go key 1 dead; MiniMax gone;
  LongCat free listed on the docs but 403/429 — recheck). Plan: newest → oldest; Shivam approved patch+pilot, full run
  needs approval.
- Chart/image pass (AR image pages + deck leftovers,
… (truncated; read tasks/STATE.md)
