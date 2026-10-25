# Worker context pack

Generated: 2026-10-25T05:49:41+05:30 · git HEAD: `d6d1306` · data root: `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data`
Staleness: regenerate with `python -m reality_engine.scripts.build_worker_context`; the `worker_context` job runs daily and a pack older than 26 h is regenerated before a worker starts.
Read this once. It replaces file-by-file orientation; the task brief is still the authority for what to do.

## 1. Repo map

Top-level tree to depth 2 (tests/fixtures skipped):
```
reality_engine/
  agent/ (4 py) — Agent module for Reality Engine.
  data/ (131 py)
  db/ (9 py) — Database services.
  harness/ (28 py) — Shared, point-in-time research harness. Importing never opens a database.
  ingestion/ (27 py) — Reality Engine Ingestion Subsystem
  notebooks/ (0 py)
  pipeline/ (19 py) — Pipeline runners.
  processing/ (41 py) — Document and image processing components.
  query/ (2 py) — One query entry point (PIPELINE_TODO Q4, first version 2026-10-19): everything known about a company at time t.
  reporting/ (3 py) — Reporting module for Reality Engine.
  scripts/ (123 py) — Operational job scripts: one module per data job; most-referenced list below
  search/ (4 py) — Search services.
  toolbelt/ (10 py) — Ready-made, read-only tools for dsh workers (Task 02).
  ui/ (2 py) — Reality Engine UI Module.
plugins/
  code-intel/ (3 py) — code-intel: LSP-backed code intelligence over the reality-engine checkout.
  dsh-worker/ (12 py) — Job manager for the local dsh-worker Codex plugin.
  dsh-workers-pane/ (0 py)
  reality-data/ (5 py) — Data access core for the reality-data MCP server.
tasks/
  ar_study/ (13 md)
  backtests/ (11 md)
  codex_tasks/ (37 md)
  council_2026-10-06/ (10 md)
  coverage/ (0 md)
  dsh_profiles/ (1 md)
  dsh_tasks/ (16 md)
  handoff/ (3 md)
  optimizations/ (11 md)
  research/ (1 md)
analysis/ (31 entries)
h02test_s6wwsqyr/ (0 entries)
h02test_vijd0qtc/ (0 entries)
```

Module one-liners (first docstring line):

### plugins/code-intel/server/
- `plugins/code-intel/server/core.py` — code-intel: LSP-backed code intelligence over the reality-engine checkout.
- `plugins/code-intel/server/lsp.py` — Minimal JSON-RPC/LSP client for one long-lived ``basedpyright-langserver``.
- `plugins/code-intel/server/server.py` — code-intel MCP server (stdio).

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
- `plugins/reality-data/server/query_embed.py` — Query-time embeddings for the 4096-d vector indexes.
- `plugins/reality-data/server/search_docs.py` — Hybrid document search over the Reality Engine data root.
- `plugins/reality-data/server/server.py` — reality-data MCP server (stdio).

### reality_engine/
- `reality_engine/__init__.py` — Reality Engine - Phase 1 Market Data Ingestion & Quantitative Reality Engine
- `reality_engine/cli.py` — Reality Engine CLI Tool
- `reality_engine/config.py` — Configuration Module for Reality Engine (Phase 1)

### reality_engine/agent/
- `reality_engine/agent/__init__.py` — Agent module for Reality Engine.
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
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/make_sample_db.py` — Build a small, public-data-only sample of the live DB so the code can be run on another machine before the full DB is fe
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/overnight_part2.py` — Queue behind overnight_pipeline.py: starts when its step 8 is done (or it has failed/finished), so the machine never idl
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/overnight_pipeline.py` — Overnight chain (resumable via analysis/overnight_state.json). Each step is isolated: a failure is logged and the chain 
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/package_for_drive.py` — Build the Drive upload pack in C:/pack_drive (originals untouched):
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/pit_validate.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/run_extract_all.py` — Run the call-date extractor over every processed concall and emit a reviewable
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/secrets_scan.py` — Scan files git would publish (tracked + untracked-not-ignored, text, <2MB) for likely secrets.
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/tariff_event_study.py` — Tariff event study per tasks/tariff_event_card_2026-09-29.md. Read-only on the DB.
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/tg_collect_video_links.py` — Collect YouTube links from selected Telegram forum topics (read-only) -> analysis/tg_video_links.csv.
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/video_load_loop.py` — Loop: load every finished transcript into the DB (frames+OCR+chunks) until all 65 batch videos are loaded.
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/video_transcribe_batch.py` — Transcribe finished videos from analysis/yt_batch_3mo.txt with whisper.cpp (Vulkan, RX 6700 XT).
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/yt_download_batch.py` — Download the batch listed in analysis/yt_batch_3mo.txt (newest first): <=1080p video+audio -> reality_engine/data/video_
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/yt_probe.py` — Metadata-only probe (no download): duration + availability for each unique video. -> analysis/yt_probe.csv

### reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/01_build_events.py` — Build the event table: BSE announcements (exact DissemDT, IST) -> (isin, t0 session, timing bucket, family).
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/02_event_engine.py` — Vectorised market-model event study over every event-day (read-only on inputs).
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/03_estimate.py` — Stratum-level estimation for the price-side information-diffusion study (numpy/pandas only).
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/04_negative_reaction_matched.py` — Negative-reaction puzzle, test 1 (closeout 2026-10-05 §3): do matched NON-announcers with the same prior-week run-up
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/05_negative_reaction_splits.py` — Negative-reaction puzzle, test 3 (closeout 2026-10-05 §3): is the announcer-vs-matched-control gap in CAR(0,1) related t
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_analysis/diffusion_study/common.py` — Shared constants for the price-side information-diffusion study (read-only on all databases).

### reality_engine/data/backups/drive_processed_2026-10-21/processed_data/concall_pilot/gemma_v3/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/concall_pilot/gemma_v3/run_pilot.py` — Gemma 4 vs MiniMax on 10 transcripts, prompt v3 + machine_check (Shivam 2026-10-20 'run it'). Free Google keys.

### reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/ctx_hb2100.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/items_hb2100.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q1.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q10.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q2.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q3.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q4.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q5.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q6.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q7.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q8.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q9.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q_err.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q_hb2100.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q_hb2100b.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q_hb2100c.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q_hb2100d.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/q_hb2100e.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_hb_tmp/schema.py` — (no docstring)

### reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb/q1.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb/q2.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb/q3.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb/q4.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb/q5.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb/q6.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb/q7.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb/q8.py` — (no docstring)

### reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb3/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb3/dump.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb3/final.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb3/hb_counts.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb3/hb_other.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb3/hb_spot.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb3/inspect2.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb3/inspect_cc.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb3/quotecheck.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb3/slow.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb3/vq.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb3/zero.py` — (no docstring)

### reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb4/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb4/q.py` — (no docstring)

### reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/ccl.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/extract.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/measure_2301.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/measure_2301b.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/pib.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/q.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/q2.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/q3.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/q4.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/sample.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/sample2.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/src.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_hb5/verify.py` — (no docstring)

### reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/count2.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/ctx.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/detail.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/dump.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/dump_json.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/extract.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/inspect_db.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/inspect_eq.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/inspect_items.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/inspect_join.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/numcheck.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/pattern.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/sample.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/scan_all.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/shortquotes.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/state_now.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/valquote.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/verify_extra.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_data/hotline/_review_tmp/verify_triton.py` — (no docstring)

### reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/inspect_calls.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/inspect_calls2.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/step1_ensemble_snapshot.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/step2_diff.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/step5_detail.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/step5_inspect.py` — (no docstring)

### reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/p0_network.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pA10_pink_cols.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pA1_ppac.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pA2_ppac_links.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pA3_ppac_tables.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pA4_ppac_js.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pA5_ICB_text.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pA6_pdfs.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pA7_fallbacks.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pA8_pinksheet.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pA9_pink_parse.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pB1_rbi.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pB2_rbi_mine.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pB3_rbi_paths.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pC1_budget.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/pC2_budget_mine.py` — (no docstring)
- `reality_engine/data/backups/drive_processed_2026-10-21/processed_logs/logs/probe/probe_lib.py` — Throwaway network probe harness. Read-only, no DB writes, no repo source edits.

### reality_engine/data/backups/restore_2026-10-21/
- `reality_engine/data/backups/restore_2026-10-21/inspect_backups.py` — (no docstring)
- `reality_engine/data/backups/restore_2026-10-21/restore_databases.py` — Audited, local-only restore of the two final PC exports. No snapshot writes.

### reality_engine/data/embed_test/
- `reality_engine/data/embed_test/colab_embed_test.py` — Colab side of the embedding retrieval test (2026-10-19, Shivam: is Qwen3-Embedding-8B worth it vs gemini-embedding-001).

### reality_engine/data/logs/
- `reality_engine/data/logs/date_resolver_coverage.py` — Coverage of the text date resolver on the 1,499 undated concall transcripts (2026-10-24 patch check).
- `reality_engine/data/logs/dsh_plugin_overnight_audit.py` — Read-only installed MCP audit. Never starts an inference worker.
- `reality_engine/data/logs/probe_lanes_20261024.py` — One-off lane probe for the concall-reader patch (2026-10-24): Go key 1/2 Beam + LongCat on both Go endpoints,
- `reality_engine/data/logs/run_provider_probes.py` — Small authorized live probes. Logs controls/usage, never credentials or reasoning text.

### reality_engine/data/logs/dsh_heartbeat_bootstrap/
- `reality_engine/data/logs/dsh_heartbeat_bootstrap/run_deepseek_harness.before.py` — Run one task headlessly in DeepSeek Harness (dsh) on an OpenCode Go model, so a Claude orchestrator can use it
- `reality_engine/data/logs/dsh_heartbeat_bootstrap/test_deepseek_harness_controls.before.py` — Local checks only: no credentials, subprocesses, inference or database access.

### reality_engine/db/
- `reality_engine/db/__init__.py` — Database services.
- `reality_engine/db/bootstrap.py` — Reality Engine Database Bootstrap Module
- `reality_engine/db/database.py` — Database Engine Module
- `reality_engine/db/fixtures.py` — Test Fixture & Isolation Utilities Module
- `reality_engine/db/migrate_master_isin.py` — Phase 1 Slice 3: Master ISIN anchor dual-write check — SQLite WAL → PG companies(isin PK)
- `reality_engine/db/readonly.py` — Read-only SQLite connections with a per-statement wall-clock guard.
- `reality_engine/db/repository.py` — Repository Module
- `reality_engine/db/seed_fundamental.py` — Seed countries + industries for Fundamental Reality Engine — PG primary, SQLite fallback demo.
- `reality_engine/db/vector_store.py` — LanceDB-backed vectors with a dependency-free JSON/NumPy fallback.

### reality_engine/harness/
- `reality_engine/harness/__init__.py` — Shared, point-in-time research harness. Importing never opens a database.
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
- `reality_engine/harness/cards/__init__.py` — Registered hypothesis implementations.
- `reality_engine/harness/cards/h01_pead.py` — H01 Card B: PIT earnings surprise on normalized snapshot facts.
- `reality_engine/harness/cards/h02_combine.py` — H01 x H02 combination rules, fixed before Stage 2 is run.
- `reality_engine/harness/cards/h02_deals.py` — H02 Card F: bulk/block deal accumulation, point-in-time from the snapshot.

### reality_engine/ingestion/
- `reality_engine/ingestion/__init__.py` — Reality Engine Ingestion Subsystem
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

### reality_engine/pipeline/
- `reality_engine/pipeline/__init__.py` — Pipeline runners.
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
- `reality_engine/processing/__init__.py` — Document and image processing components.
- `reality_engine/processing/ar_row_guards.py` — Guards for the annual-report row clean-up pass (tasks/AR_INGESTION_PROTOCOL.md, LLM stage a).
- `reality_engine/processing/attention_ranker.py` — Tier-3 attention ranking + morning digest (news-feed Tier-2/3 slice).
- `reality_engine/processing/business_peer_graph.py` — Business-substance cross-map: analog companies by what they actually do.
- `reality_engine/processing/business_profiler.py` — Wave A2 (Task A2): Business Model Profiles canonical persistence.
- `reality_engine/processing/capacity_governor.py` — Capacity governor — evidence-gated explainer-capacity expansion.
- `reality_engine/processing/causal_engine.py` — SQLite-backed causal knowledge graph operations.
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
- `reality_engine/processing/vision_engine.py` — Multimodal Vision Alpha Pipeline - keyframe extraction + VisualArtifact schema.

### reality_engine/query/
- `reality_engine/query/__init__.py` — (no docstring)
- `reality_engine/query/state.py` — One query entry point (PIPELINE_TODO Q4, first version 2026-10-19): everything known about a company at time t.

### reality_engine/reporting/
- `reality_engine/reporting/__init__.py` — Reporting module for Reality Engine.
- `reality_engine/reporting/notifier.py` — Wave B — Telegram alerts + 23:00 nightly digest (stdlib only, no new deps).
- `reality_engine/reporting/writer.py` — Report Writer Module

### reality_engine/scripts/
- `reality_engine/scripts/ar_ocr_reread.py` — Free re-read of annual-report pages whose text layer is unusable (garbled OCR, scans, digit-encoding fonts).
- `reality_engine/scripts/ar_queue.py` — Annual-report work queue for readers that only answer inside the OpenCode app (OpenCode Zen free models).
- `reality_engine/scripts/ar_review.py` — Annual-report extraction review, run after every 200 newly finished reports (Shivam 2026-10-13: "keep optimizing after
- `reality_engine/scripts/ar_wrong_company_scan.py` — Find annual-report PDFs in ar_docs that are another company's report. Read-only; free local checks only.
- `reality_engine/scripts/ar_yoy.py` — Year-over-year page skip for annual-report reading (to-do 2026-10-13 in tasks/STATE.md).
- `reality_engine/scripts/backfill_call_rows.py` — Backfill missing ``eod_scrip_calls`` rows for attribution dates.
- `reality_engine/scripts/backfill_fiscal_periods.py` — Backfill body-genuine fiscal-period labels on document_chunks (findings §11).
- `reality_engine/scripts/backfill_index_ohlc.py` — Backfill universe-index OHLC rows into ``nse_index_breadth``.
- `reality_engine/scripts/backfill_raw_document_symbols.py` — Backfill ``raw_documents.symbol`` / ``.isin`` (+ ``.symbol_source``).
- `reality_engine/scripts/backup_dbs_to_drive.py` — Back up the project databases to Google Drive (Shivam 2026-10-19: uploads only 05:00-13:00 IST, every day).
- `reality_engine/scripts/bench_method_a.py` — bench_method_a.py — Method A: Tightened filing_discovery._classify benchmark
- `reality_engine/scripts/bench_method_b.py` — bench_method_b.py — Method B: Title-based DB backfill reclassification benchmark
- `reality_engine/scripts/bench_method_c.py` — Method C: Post-download content classifier benchmark (PyMuPDF + GPU OCR fallback)
- `reality_engine/scripts/boot_recover.py` — Crash recovery: bring every job back after a reboot or power cut, with nobody logged in (Shivam 2026-10-19).
- `reality_engine/scripts/build_chunk_vector_index.py` — Build (or rebuild) the local dense-retrieval index over document_chunks.
- `reality_engine/scripts/build_insider_trades.py` — Normalized insider trades (insider_trades_v2) from the raw feeds already on disk.
- `reality_engine/scripts/build_query_indexes.py` — Missing indexes and text indexes for the query layer (PIPELINE_TODO Q3, 2026-10-19). Idempotent: every statement is
- `reality_engine/scripts/build_security_master.py` — Security master from the exchanges' own files (2026-10-19, Shivam: survivorship-safe universe).
- `reality_engine/scripts/build_tax_rules.py` — Tax-rule table for the backtest harness (PIPELINE_TODO A1, 2026-10-19). Table `tax_rules` in equity_intelligence.db.
- `reality_engine/scripts/build_truth_snapshot.py` — Truth layer: build a dated, read-only research snapshot of clean daily prices.
- `reality_engine/scripts/build_worker_context.py` — Generate the worker context pack (``tasks/worker_context/CONTEXT.md``).
- `reality_engine/scripts/claude_page_queue.py` — Hand-off between the deck-figure database and Claude Code helper agents (Claude Haiku 5.5), which cannot be called
- `reality_engine/scripts/cleanup_verify.py` — Which local PDFs / decks are safe to delete? (Shivam 2026-10-20: free the PC disk; the laptop is the workstation.)
- `reality_engine/scripts/colab_embed_test.py` — Colab side of the embedding retrieval test (2026-10-19, Shivam: is Qwen3-Embedding-8B worth it vs gemini-embedding-001).
- `reality_engine/scripts/concall_deepseek.py` — 2026 concall transcripts -> DeepSeek V4.1 Flash on OpenCode Go (Shivam, 2026-10-18: 2026 transcripts are read by
- `reality_engine/scripts/concall_deepseek_check.py` — Validation of concall_facts.db against its sources (2026-10-18, Shivam: test labels / PIT / metadata on a sample
- `reality_engine/scripts/concall_facts_checks.py` — Verified-vs-inferred flags for DeepSeek concall facts + our own guidance direction (2026-10-18).
- `reality_engine/scripts/concall_period.py` — Normalise the quarter / fiscal year a concall discusses (Indian FY: Q1 = Apr-Jun; FY27 = Apr 2026 - Mar 2027).
- `reality_engine/scripts/concall_pilot.py` — Concall semantic-extraction pilot (2026-10-18): the same prompt (data/concall_pilot/prompt.md) on 25 transcripts,
- `reality_engine/scripts/concall_query_test.py` — Can we query the DeepSeek concall facts? (2026-10-18 pilot of 118 transcripts, Shivam: test before the full run.)
- `reality_engine/scripts/coverage_report.py` — Coverage report: for every company that traded on BSE or NSE in a year (2019 onwards), which datasets we hold.
- `reality_engine/scripts/deck_zen_test.py` — 40-page deck reader test for OpenCode Zen free models (they answer only inside OpenCode, so each page is one
- `reality_engine/scripts/deepseek_heartbeat.py` — DeepSeek heartbeat (Shivam, 2026-10-20): wakes DeepSeek, never Claude. Run hourly by the Windows task
- `reality_engine/scripts/discover_bse_feed_docs.py` — Add filings from the harvested BSE announcement feed (analysis/bse_announcements.db, every BSE company, 2020-01 ->
- `reality_engine/scripts/drive_upload_check.py` — Which local PDFs / decks are not on Google Drive yet (2026-10-19, after the power cut stopped Shivam's browser upload).
- `reality_engine/scripts/drop_debt_issuer_reports.py` — Drop annual reports filed under BSE debt-instrument scrips (scrip codes 9xxxxx: NCDs/bonds), keeping rating reports
- `reality_engine/scripts/dsh_batch.py` — Run a JSONL of worker tasks in parallel through run_deepseek_harness and print ONE compact summary table.
- `reality_engine/scripts/dsh_heartbeat.py` — Heartbeat supervision for one-shot dsh runs.
- `reality_engine/scripts/embed_ar_rerank_test.py` — Reranker leg of the annual-report embedding pilot (2026-10-24, Shivam: can Nemotron-3-Embed-1B-NVFP4 + a reranker
- `reality_engine/scripts/embed_ar_test.py` — Annual-report embedding pilot on DeepInfra (2026-10-24, Shivam: pick the AR embedder on cost-to-value, as the
- `reality_engine/scripts/embed_model_test.py` — Embedding-model retrieval test on our own concall chunks (2026-10-18, Shivam: test before switching from bge-small).
- `reality_engine/scripts/embed_prototype_compare.py` — Prototype: bge-small-en-v1.5 (incumbent, 384d) vs bge-base-en-v1.5 (challenger, 768d).
- `reality_engine/scripts/embed_video_chunks.py` — Embed YouTube/Telegram video chunks that have no embedding yet (bge-small-en-v1.5, 384-d, DirectML on the RX 6700 XT,
- `reality_engine/scripts/extract_deck_figures.py` — Extract the figures printed on investor-presentation slides with OpenCode Go vision models.
- `reality_engine/scripts/fetch_board_meetings.py` — Board-meeting calendar, NSE (PIPELINE_TODO phase C: forward board-meeting calendar / results dates ahead; 2026-10-19).
- `reality_engine/scripts/fetch_bse_announcements_daily.py` — Market-wide BSE announcements by date -> analysis/bse_announcements.db table `ann` (2026-10-19).
- `reality_engine/scripts/fetch_bse_annual_report_dates.py` — Date the annual reports in corporate_documents from BSE's own annual-report list.
- `reality_engine/scripts/fetch_bse_api_raw.py` — Raw BSE disclosure fetcher (download only, no DB writes).
- `reality_engine/scripts/fetch_decks.py` — Download historical investor-presentation PDFs (2021 onwards) from BSE and, for companies listed only on NSE,
- `reality_engine/scripts/fetch_etf_nav.py` — ETF prices, NAV and premium (PIPELINE_TODO B1, 2026-10-19). Tables in equity_intelligence.db:
- `reality_engine/scripts/fetch_fiidii_moneycontrol.py` — Daily FII / DII cash-market flows from Moneycontrol (third-party archive; approved by
- `reality_engine/scripts/fetch_index_tri.py` — Total-return indices for the benchmark rule (PIPELINE_TODO B2, 2026-10-19). Table `index_tri` in equity_intelligence.db.
- `reality_engine/scripts/fetch_macro_docs.py` — Fetch macro policy documents 2019-2026 with their real publication dates, then ingest them (2026-10-17).
- `reality_engine/scripts/fetch_market_raw.py` — Raw market-data fetcher (download only, no DB writes).
- `reality_engine/scripts/fetch_missed_ar_files.py` — Fetch annual-report files BSE lists but we never downloaded, and register them as ANNUAL_REPORT filings (2026-10-16).
- `reality_engine/scripts/fetch_nsdl_raw.py` — Raw NSDL FPI report fetcher (download only, no DB writes).
- `reality_engine/scripts/fetch_nse_api_raw.py` — Raw NSE disclosure fetcher (download only, no DB writes).
- `reality_engine/scripts/fetch_nse_industry.py` — NSE industry classification per listed company (2026-10-19, for A3 policy -> company mapping and sector peers).
- `reality_engine/scripts/fetch_nse_pr.py` — NSE daily circuit hits, price bands and surveillance stages (PIPELINE_TODO phase C, 2026-10-19).
- `reality_engine/scripts/fetch_shareholding.py` — Quarterly shareholding pattern (PIPELINE_TODO B3, 2026-10-19). Tables in equity_intelligence.db:
- `reality_engine/scripts/go_session.py` — Stable `x-opencode-session` ids for every OpenCode Go call (Shivam, 2026-10-20: standing rule for all routing calls).
- `reality_engine/scripts/ingest_annual_reports.py` — Annual-report fact extraction with the free readers that passed the AR must-find test (tasks/ar_study/free_test):
- `reality_engine/scripts/ingest_video_batch.py` — Frames + OCR + DB load for transcribed member videos (Telegram Daily Bytes etc.).
- `reality_engine/scripts/install_annual_drain_task.py` — Register the hourly annual-drain watchdog as a Windows Scheduled Task.
- `reality_engine/scripts/load_index_membership.py` — Load official index constituent CSVs (niftyindices.com) into index_membership.
- `reality_engine/scripts/load_market_raw.py` — Load raw market files (from fetch_market_raw.py / fetch_nse_api_raw.py) into the DB.
- `reality_engine/scripts/measure_cross_map_quality.py` — Measure cross-map quality: does an anchor's neighbourhood land in its own industry?
- `reality_engine/scripts/merge_lane_db.py` — Worktree lane DB merger for Reality Engine.
- `reality_engine/scripts/merge_placeholder_isins.py` — Merge every remaining INE_AUTO_* placeholder ISIN into its real ISIN, across all tables (2026-10-16).
- `reality_engine/scripts/migrate_event_version.py` — Idempotent event-date/version migration for document tables (handover §4 item 1).
- `reality_engine/scripts/migrate_vector_store.py` — One-time migration: vectors.json -> vectors.npy + vectors_meta.json.
- `reality_engine/scripts/new_reader_check.py` — Daily check for new free readers (STATE to-do 1, 2026-10-13). Run once a day by the resource watchdog; safe to run
- `reality_engine/scripts/parse_nse_results_xbrl.py` — Parse the NSE financial-results XBRL files into a dated quarterly table.
- `reality_engine/scripts/pib_feed.py` — PIB (Press Information Bureau) English releases: daily feed + backfill (2026-10-19; Shivam: government policy change,
- `reality_engine/scripts/pib_regional.py` — PIB phase 2 (PIPELINE_TODO A2, 2026-10-19): Hindi / Urdu releases of PIB Delhi and every regional PIB office in every
- `reality_engine/scripts/policy_register.py` — Policy register: dated policy changes extracted from Government / RBI documents (2026-10-19, Shivam: policy change -
- `reality_engine/scripts/profile_tuner.py` — Overnight profile tuner (2026-10-13, Shivam: "do the same for the Zen models when they come back"). Runs detached
- `reality_engine/scripts/query_speed_check.py` — Query speed check (PIPELINE_TODO Q1, 2026-10-19): a fixed list of the queries backtests and analysis run, each with a
- `reality_engine/scripts/reader_quality_test.py` — 40-page reader quality test for deck pages (Shivam's rule: a new reader needs identifiable >= ~85%, zero misread
- `reality_engine/scripts/reembed_gemma.py` — Re-embed every document chunk with EmbeddingGemma-300M (Shivam approved 2026-10-19).
- `reality_engine/scripts/reembed_qwen_nebius.py` — Qwen3-Embedding-8B over Nebius Token Factory for the priority tiers (Shivam, 2026-10-20: pay ~$2 so transcripts,
- `reality_engine/scripts/refetch_all_ip_method_c.py` — Refetch all true Investor Presentations with Method C, delete notices immediately.
- `reality_engine/scripts/rekey_placeholder_isins.py` — Re-key document and annual-report rows from placeholder INE_AUTO_* ISINs to the real ISIN (2026-10-16).
- `reality_engine/scripts/repair_transcript_dates.py` — Repair filing dates in the search layer (2026-10-18; --types widens it beyond concall transcripts).
- `reality_engine/scripts/resolve_results_isin.py` — Trading ISIN for every results XBRL filing (2026-10-19). New table results_xbrl.db `filings_isin`; `filings` is untouche
- `reality_engine/scripts/resource_watchdog.py` — Machine-wide resource watchdog: keeps the long jobs alive and records every case of wasted compute.
- `reality_engine/scripts/run_annual_report_ingest.py` — Annual-report ingestion: turn the 26k indexed-but-never-downloaded filings into substrate.
- `reality_engine/scripts/run_business_peer_graph.py` — Build the business-substance analog cross-map over the embedded corpus.
- `reality_engine/scripts/run_deepseek_harness.py` — Run one task headlessly in DeepSeek Harness (dsh) on an OpenCode Go model, so a Claude orchestrator can use it
- `reality_engine/scripts/run_distill_all.py` — Wave 0 — Substrate promotion runner for ALL macro raw_documents.
- `reality_engine/scripts/run_entity_graph.py` — Build the unified entity cross-map (A + B + C) from substrate only.
- `reality_engine/scripts/run_eod_market.py` — End-of-day market + disclosure update (Shivam OK 2026-10-19). Scheduled task 'RealityEngine-EODMarket', weekdays
- `reality_engine/scripts/run_factor_peer.py` — Peer 1 (Factor/Statistical) substrate promotion runner.
- `reality_engine/scripts/run_full_suite.py` — Full-suite runner that writes a machine-readable verdict (shell pipes are unreliable here).
- `reality_engine/scripts/run_ingestion_queue.py` — Ingestion queue: run every pending filing/backfill stage ONE AT A TIME.
- `reality_engine/scripts/run_moe_eod.py` — Final Wave - MoE seeding & EOD correction loop (continuous improvement engine).
- `reality_engine/scripts/run_offer_drhp_backfill.py` — Resumable DRHP/Offer-document download + ingest + distill driver (v3).
- `reality_engine/scripts/run_offer_pdf_resolve.py` — Fan-out PDF resolver for SEBI offer-document filings.
- `reality_engine/scripts/run_peer_graph.py` — Analog peer graph promotion — precompute substrate nearest neighbours.
- `reality_engine/scripts/run_pib_ingest.py` — PIB (Press Information Bureau) release ingestion — the macro transmission channel.
- `reality_engine/scripts/run_policy_peer.py` — Peer 3 (Policy Macro) — isolated substrate promotion runner.
- `reality_engine/scripts/run_quality_peer.py` — Peer 2 (Business Quality / Moat) substrate promotion runner.
- `reality_engine/scripts/run_rag_slice.py` — Bounded detached RAG slice: archive + ingest in idempotent bounded batches.
- `reality_engine/scripts/run_skill_loop.py` — Walk-forward skill loop driver: fit on early occurrences, evaluate on later ones.
- `reality_engine/scripts/run_substrate_hygiene.py` — Substrate trust layer promotion — materialize quarantine keys, print degradation.
- `reality_engine/scripts/run_supply_peer.py` — Peer 4 — Supply Chain substrate promotion (isolated, parallel-safe).
- `reality_engine/scripts/seed_track_record.py` — Seed the audited portfolio track record from existing history.
- `reality_engine/scripts/session_digest.py` — Whole-conversation context for worker models (Shivam, 2026-10-20: "how would DeepSeek know what happened in the whole
- `reality_engine/scripts/setup_gdrive_readonly.py` — Create an rclone remote 'gdrive_ro' with READ-ONLY access to the whole Google Drive (2026-10-19).
- `reality_engine/scripts/setup_worker_env.py` — Install the packages dsh workers repeatedly need into the main Python.
- `reality_engine/scripts/snapshot_research_tables.py` — Research tables for the nightly DuckDB analysis snapshot (PIPELINE_TODO Q2, 2026-10-19).
- `reality_engine/scripts/state_check.py` — Check for reality_engine/query/state.py (PIPELINE_TODO Q4): leak test + latency over random (isin, t).
- `reality_engine/scripts/state_handcheck.py` — Hand check of state(isin, t) against raw sources (PIPELINE_TODO Q4, 2026-10-19): 20 random companies with 2025-26
- `reality_engine/scripts/tag_telegram_posts.py` — Tag Telegram posts with companies using screener.in/company/<slug> links found in the message text or buttons.
- `reality_engine/scripts/tag_video_chunks.py` — Tag YouTube/Telegram video chunks with company symbols (title-guided + exact-name matching).
- `reality_engine/scripts/tg_backfill.py` — Backfill Telegram forum-topic history (TEXT + LINKS + timestamps only; no media downloads).
- `reality_engine/scripts/tg_company_mentions.py` — Companies named in Telegram topics (Financially Free community), with point-in-time post times (2026-10-18).
- `reality_engine/scripts/tg_list_topics.py` — Read-only: list forum topics of a Telegram channel with message counts and date range.
- `reality_engine/scripts/tg_login.py` — One-time interactive Telegram login. Run this yourself in a terminal (it asks for your phone
- `reality_engine/scripts/tg_orders.py` — Orders from the Telegram 'Big Orders' topic (7) -> tg_orders + tg_order_schedule (2026-10-19).
- `reality_engine/scripts/tg_pead_signals.py` — PEAD signal table from the Financially Free 'PEAD' Telegram topic (683), for backtesting and transcript priority.
- `reality_engine/scripts/weekly_sebi_ingest.py` — Weekly SEBI filing ingestion (new DRHP/Prospectus filings -> dense substrate).
- `reality_engine/scripts/worker_context.py` — Live-state context file for worker models (Shivam, 2026-10-20: a worker cannot answer from information it never got;

### reality_engine/search/
- `reality_engine/search/__init__.py` — Search services.
- `reality_engine/search/chunk_vector_index.py` — Local dense-retrieval index over ``document_chunks.embedding``.
- `reality_engine/search/hybrid_search.py` — Lexical plus dense search using reciprocal rank fusion.
- `reality_engine/search/intel_search.py` — Tier-aware unified search over ``intelligence_fts`` (news-feed v1).

### reality_engine/toolbelt/
- `reality_engine/toolbelt/__init__.py` — Ready-made, read-only tools for dsh workers (Task 02).
- `reality_engine/toolbelt/_common.py` — Shared helpers for the toolbelt CLIs.
- `reality_engine/toolbelt/cost_ledger.py` — Append-only paid-call ledger with a hard budget gate.
- `reality_engine/toolbelt/coverage_peek.py` — One command: what data do we hold for a symbol, per store, with row counts and date ranges.
- `reality_engine/toolbelt/drive_fetch.py` — Fetch a document from ``gdrive:InfoDiffusion_archive`` by path, sha256 or stale DB path.
- `reality_engine/toolbelt/find_docs.py` — Find a company's documents across every store and report their real state.
- `reality_engine/toolbelt/job_peek.py` — Compact view of a dsh job directory without loading whole event files.
- `reality_engine/toolbelt/mod_test.py` — Run a Claude Code mod's checks the way this sandbox actually allows.
- `reality_engine/toolbelt/render_pages.py` — Render PDF pages to PNG, or dump the text layer with the pipeline's low-text rule.
- `reality_engine/toolbelt/sample_rows.py` — Random row samples from a live SQLite store without scanning it.

### reality_engine/ui/
- `reality_engine/ui/__init__.py` — Reality Engine UI Module.
- `reality_engine/ui/dashboard.py` — Reality Engine - Streamlit Equity Intelligence Dashboard

### Most-referenced scripts

Ranked by mentions in `tasks/STATE.md`, `plugins/dsh-worker/jobs.yaml` and the 20 newest `tasks/dsh_tasks/*.md` briefs:

- `reality_engine/scripts/ar_queue.py` (22 refs) — Annual-report work queue for readers that only answer inside the OpenCode app (OpenCode Zen free models).
- `reality_engine/scripts/ingest_annual_reports.py` (16 refs) — Annual-report fact extraction with the free readers that passed the AR must-find test (tasks/ar_study/free_test):
- `reality_engine/scripts/resource_watchdog.py` (13 refs) — Machine-wide resource watchdog: keeps the long jobs alive and records every case of wasted compute.
- `reality_engine/scripts/boot_recover.py` (10 refs) — Crash recovery: bring every job back after a reboot or power cut, with nobody logged in (Shivam 2026-10-19).
- `reality_engine/scripts/concall_deepseek.py` (9 refs) — 2026 concall transcripts -> DeepSeek V4.1 Flash on OpenCode Go (Shivam, 2026-10-18: 2026 transcripts are read by
- `reality_engine/scripts/extract_deck_figures.py` (8 refs) — Extract the figures printed on investor-presentation slides with OpenCode Go vision models.
- `reality_engine/scripts/new_reader_check.py` (8 refs) — Daily check for new free readers (STATE to-do 1, 2026-10-13). Run once a day by the resource watchdog; safe to run
- `reality_engine/scripts/deepseek_heartbeat.py` (6 refs) — DeepSeek heartbeat (Shivam, 2026-10-20): wakes DeepSeek, never Claude. Run hourly by the Windows task
- `reality_engine/scripts/pib_regional.py` (6 refs) — PIB phase 2 (PIPELINE_TODO A2, 2026-10-19): Hindi / Urdu releases of PIB Delhi and every regional PIB office in every
- `reality_engine/scripts/claude_page_queue.py` (5 refs) — Hand-off between the deck-figure database and Claude Code helper agents (Claude Haiku 5.5), which cannot be called
- `reality_engine/scripts/concall_pilot.py` (5 refs) — Concall semantic-extraction pilot (2026-10-18): the same prompt (data/concall_pilot/prompt.md) on 25 transcripts,
- `reality_engine/scripts/fetch_nse_api_raw.py` (5 refs) — Raw NSE disclosure fetcher (download only, no DB writes).
- `reality_engine/scripts/load_market_raw.py` (5 refs) — Load raw market files (from fetch_market_raw.py / fetch_nse_api_raw.py) into the DB.
- `reality_engine/scripts/policy_register.py` (5 refs) — Policy register: dated policy changes extracted from Government / RBI documents (2026-10-19, Shivam: policy change -
- `reality_engine/scripts/run_annual_report_ingest.py` (5 refs) — Annual-report ingestion: turn the 26k indexed-but-never-downloaded filings into substrate.
- `reality_engine/scripts/worker_context.py` (5 refs) — Live-state context file for worker models (Shivam, 2026-10-20: a worker cannot answer from information it never got;
- `reality_engine/scripts/ar_yoy.py` (4 refs) — Year-over-year page skip for annual-report reading (to-do 2026-10-13 in tasks/STATE.md).
- `reality_engine/scripts/coverage_report.py` (4 refs) — Coverage report: for every company that traded on BSE or NSE in a year (2019 onwards), which datasets we hold.
- `reality_engine/scripts/fetch_decks.py` (4 refs) — Download historical investor-presentation PDFs (2021 onwards) from BSE and, for companies listed only on NSE,
- `reality_engine/scripts/fetch_market_raw.py` (4 refs) — Raw market-data fetcher (download only, no DB writes).
- `reality_engine/scripts/run_eod_market.py` (4 refs) — End-of-day market + disclosure update (Shivam OK 2026-10-19). Scheduled task 'RealityEngine-EODMarket', weekdays
- `reality_engine/scripts/build_insider_trades.py` (3 refs) — Normalized insider trades (insider_trades_v2) from the raw feeds already on disk.
- `reality_engine/scripts/build_truth_snapshot.py` (3 refs) — Truth layer: build a dated, read-only research snapshot of clean daily prices.
- `reality_engine/scripts/concall_deepseek_check.py` (3 refs) — Validation of concall_facts.db against its sources (2026-10-18, Shivam: test labels / PIT / metadata on a sample
- `reality_engine/scripts/concall_facts_checks.py` (3 refs) — Verified-vs-inferred flags for DeepSeek concall facts + our own guidance direction (2026-10-18).
- `reality_engine/scripts/concall_query_test.py` (3 refs) — Can we query the DeepSeek concall facts? (2026-10-18 pilot of 118 transcripts, Shivam: test before the full run.)
- `reality_engine/scripts/discover_bse_feed_docs.py` (3 refs) — Add filings from the harvested BSE announcement feed (analysis/bse_announcements.db, every BSE company, 2020-01 ->
- `reality_engine/scripts/drive_upload_check.py` (3 refs) — Which local PDFs / decks are not on Google Drive yet (2026-10-19, after the power cut stopped Shivam's browser upload).
- `reality_engine/scripts/fetch_bse_annual_report_dates.py` (3 refs) — Date the annual reports in corporate_documents from BSE's own annual-report list.
- `reality_engine/scripts/go_session.py` (3 refs) — Stable `x-opencode-session` ids for every OpenCode Go call (Shivam, 2026-10-20: standing rule for all routing calls).
- `reality_engine/scripts/query_speed_check.py` (3 refs) — Query speed check (PIPELINE_TODO Q1, 2026-10-19): a fixed list of the queries backtests and analysis run, each with a
- `reality_engine/scripts/tg_orders.py` (3 refs) — Orders from the Telegram 'Big Orders' topic (7) -> tg_orders + tg_order_schedule (2026-10-19).
- `reality_engine/scripts/tg_pead_signals.py` (3 refs) — PEAD signal table from the Financially Free 'PEAD' Telegram topic (683), for backtesting and transcript priority.
- `reality_engine/scripts/backup_dbs_to_drive.py` (2 refs) — Back up the project databases to Google Drive (Shivam 2026-10-19: uploads only 05:00-13:00 IST, every day).
- `reality_engine/scripts/embed_ar_test.py` (2 refs) — Annual-report embedding pilot on DeepInfra (2026-10-24, Shivam: pick the AR embedder on cost-to-value, as the
- `reality_engine/scripts/embed_model_test.py` (2 refs) — Embedding-model retrieval test on our own concall chunks (2026-10-18, Shivam: test before switching from bge-small).
- `reality_engine/scripts/fetch_board_meetings.py` (2 refs) — Board-meeting calendar, NSE (PIPELINE_TODO phase C: forward board-meeting calendar / results dates ahead; 2026-10-19).
- `reality_engine/scripts/fetch_bse_api_raw.py` (2 refs) — Raw BSE disclosure fetcher (download only, no DB writes).
- `reality_engine/scripts/fetch_etf_nav.py` (2 refs) — ETF prices, NAV and premium (PIPELINE_TODO B1, 2026-10-19). Tables in equity_intelligence.db:
- `reality_engine/scripts/fetch_fiidii_moneycontrol.py` (2 refs) — Daily FII / DII cash-market flows from Moneycontrol (third-party archive; approved by

## 2. Data map

Data root: `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data` (`REALITY_DATA_ROOT`; read-only from a worktree). Never write without an explicit instruction.

| DB | file | size | tables | use |
|---|---|---|---|---|
| truth_duckdb | `truth_2026-10-19.duckdb` | 8.5 GB | 63 | Dated, read-only research snapshot (2026-10-19) built from the live SQLite DBs: clean entity-level prices with split/bonus/dividend adjustment and point-in-time known_at timestamps (date-only sources stamped 23:59:59 IST), plus consolidated results/AR/deck/concall/ownership/policy tables. Prefer this for historical/as-of research; SQLite is the live source with newer rows and full text. |
| equity_intelligence | `equity_intelligence.db` | 50.1 GB | 123 | Live primary equity database: company master, normalized daily prices, financials, corporate actions/documents, ownership/market flows, policy/macro/ripple layers, substrate analytics, Telegram signals and quarantine. Use it for latest/live data and full text; use truth_duckdb for adjusted price history and PIT-stamped research tables. Mixed raw and derived; check per-table notes. |
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
| `reality_engine.config` | test_agent_and_reporting.py, test_bootstrap.py, test_news_retention.py, test_v2_ingestion_adapters.py |
| `reality_engine.db.database` | test_action_thesis.py, test_attention_ranker.py, test_backfill_call_rows.py, test_bootstrap.py, test_bse_backfill.py, test_bse_fundamentals_client.py, test_catchup_scheduler.py, test_continuous_loop.py, test_deals_client.py, test_derived_substrate.py, test_desk_backtest.py, test_distillation_macro.py, test_distilled_expansion.py, test_document_industry_tag.py, test_document_pit.py, test_ensemble_ranker.py, test_ensemble_weighted.py, test_eod_corrector.py, test_event_graph.py, test_factor_loaders.py, test_factor_spine.py, test_financial_denominator.py, test_fiscal_extraction.py, test_forecast_capacity.py, test_horizon_excess.py, test_index_backfill.py, test_insider_trades.py, test_intel_search.py, test_lifecycle_pruning.py, test_macro_ingest.py, test_macro_pdf_fetcher.py, test_master_bse_admission.py, test_master_upsert.py, test_moat_backfill.py, test_moe_all_universe.py, test_move_attribution.py, test_news_announcements.py, test_news_explainer.py, test_news_feed_client.py, test_news_retention.py, test_news_vision.py, test_nightly_alpha.py, test_peer_graph_and_hygiene.py, test_perf_guards.py, test_policy_coverage.py, test_policy_eni.py, test_policy_press_client.py, test_portfolio_ledger.py, test_pua_fallback.py, test_repo_identity.py, test_repo_lane.py, test_rumor_backfill.py, test_rumor_scorer.py, test_screener_substrate_routing.py, test_sip_backtest.py, test_sip_signals.py, test_skill_loop.py, test_supply_chain.py, test_telegram_hardening.py, test_v2_ingestion_adapters.py |
| `reality_engine.db.fixtures` | test_bootstrap.py |
| `reality_engine.db.readonly` | test_readonly.py |
| `reality_engine.db.repository` | test_action_thesis.py, test_attention_ranker.py, test_backfill_call_rows.py, test_bootstrap.py, test_deals_client.py, test_derived_substrate.py, test_distillation_macro.py, test_distilled_expansion.py, test_document_industry_tag.py, test_document_pit.py, test_ensemble_ranker.py, test_ensemble_weighted.py, test_eod_corrector.py, test_factor_spine.py, test_financial_denominator.py, test_forecast_capacity.py, test_index_backfill.py, test_insider_trades.py, test_intel_search.py, test_macro_ingest.py, test_macro_pdf_fetcher.py, test_master_bse_admission.py, test_master_upsert.py, test_moat_backfill.py, test_moe_all_universe.py, test_move_attribution.py, test_news_announcements.py, test_news_explainer.py, test_news_feed_client.py, test_news_vision.py, test_peer_graph_and_hygiene.py, test_policy_coverage.py, test_policy_eni.py, test_policy_press_client.py, test_portfolio_ledger.py, test_quant_hardening.py, test_repo_identity.py, test_repo_lane.py, test_rumor_scorer.py, test_screener_substrate_routing.py, test_sip_signals.py, test_supply_chain.py, test_telegram_hardening.py, test_v2_ingestion_adapters.py |
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
| `reality_engine.ingestion.deals_client` | test_deals_client.py |
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
| `reality_engine.processing.composite_screener` | test_action_thesis.py, test_ensemble_ranker.py, test_policy_coverage.py, test_quant_hardening.py |
| `reality_engine.processing.desk_backtest` | test_desk_backtest.py |
| `reality_engine.processing.distillation_engine` | test_distillation_macro.py, test_distilled_expansion.py |
| `reality_engine.processing.ensemble_ranker` | test_action_thesis.py, test_eod_corrector.py, test_move_attribution.py |
| `reality_engine.processing.eod_corrector` | test_eod_corrector.py, test_move_attribution.py |
| `reality_engine.processing.event_graph` | test_eod_corrector.py, test_event_graph.py |
| `reality_engine.processing.factor_loaders` | test_factor_loaders.py |
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
| `reality_engine.reporting.writer` | test_action_thesis.py, test_agent_and_reporting.py |
| `reality_engine.scripts.backfill_call_rows` | test_backfill_call_rows.py |
| `reality_engine.scripts.backfill_fiscal_periods` | test_fiscal_extraction.py |
| `reality_engine.scripts.backfill_index_ohlc` | test_index_backfill.py |
| `reality_engine.scripts.backfill_raw_document_symbols` | test_raw_document_symbols.py |
| `reality_engine.scripts.build_insider_trades` | test_insider_trades.py |
| `reality_engine.scripts.dsh_heartbeat` | test_dsh_worker_plugin.py |
| `reality_engine.scripts.embed_prototype_compare` | test_embed_prototype.py |
| `reality_engine.scripts.extract_deck_figures` | test_extract_deck_figures.py |
| `reality_engine.scripts.merge_lane_db` | test_merge_lane_db.py |
| `reality_engine.scripts.resource_watchdog` | test_resource_watchdog.py |
| `reality_engine.scripts.run_deepseek_harness` | test_deepseek_harness_controls.py, test_dsh_heartbeat.py |
| `reality_engine.scripts.seed_track_record` | test_portfolio_ledger.py |
| `reality_engine.search.intel_search` | test_intel_search.py, test_rumor_backfill.py |
| `reality_engine.toolbelt.cost_ledger` | test_toolbelt.py |
| `reality_engine.toolbelt.coverage_peek` | test_coverage_peek.py |
| `reality_engine.toolbelt.drive_fetch` | test_toolbelt.py |
| `reality_engine.toolbelt.find_docs` | test_toolbelt.py |
| `reality_engine.toolbelt.job_peek` | test_toolbelt.py |
| `reality_engine.toolbelt.mod_test` | test_toolbelt.py |
| `reality_engine.toolbelt.render_pages` | test_toolbelt.py |
| `reality_engine.toolbelt.sample_rows` | test_toolbelt.py |
| `reality_engine.ui.dashboard` | test_cli_and_dashboard.py |

## 5. Sandbox limits + workarounds

# Worker sandbox, temp, write scopes and detached processes

Written 2026-10-25 (Task 03) from the live dsh 0.2.1 sources and the two profile
patches. Read this before starting a worker that needs to install packages,
write outside the worktree, commit, or launch something long-lived.

## 1. What `permission` actually does (verified mapping)

`start_worker(permission=...)` → `run_deepseek_harness.py --permission` → the
launcher sets `DSH_PERMISSION_MODE` → `dsh-base/cordis.patch.yml` reads it in two
rows:

| `permission` | `dsh-sandbox-policy.mode` | `dsh-user-approval.policy` | Effect |
|---|---|---|---|
| `read-only` | `read-only` | `ask` | No write grants. Confined pwsh gets no private temp either, so `tempfile.mkdtemp()` fails. |
| `workspace-write` (default for mutating jobs) | `workspace-write` | `ask` | Writes under the session cwd (the `--cwd` workspace) plus a per-session private temp dir; `dsh-pwsh-sandbox` rewrites `TMP`/`TEMP` to that private dir for every confined command. |
| `danger-full-access` | `danger-full-access` | `never` | No confinement; the sandbox provider is never consulted. |

Key facts:

- The **writable root is the session cwd**, i.e. the `--cwd` passed to dsh
  (`workspace` / the worktree). `sandbox-policy.workspaceRoot` is only a
  fallback for calls without a session cwd.
- Windows enforcement is the **ACL restricted-token rung**
  (`dsh-sandbox-windows-acl`): a `WRITE_RESTRICTED` token whose restricting SIDs
  carry the workspace SID (deterministic per workspace path) and a random
  per-session temp SID, lowered to Low integrity. It is reported as `partial`
  (hard links alias file objects, reads are unconfined).
- **There is no extra-writable-roots setting in dsh 0.2.1.** One writable root
  per session; the fs fence (`dsh-fs-sandbox`) and the pwsh runner both derive
  their roots from the same policy. A junction/symlink inside the workspace to
  `reality_engine/data` does not help: both the fence and the ACL token check the
  resolved target.
- The fs fence (`dsh-fs-sandbox`) also allows `os.tmpdir()` in
  `workspace-write`, but the confined pwsh child is the stricter boundary.

## 2. Per-job temp and caches (supervisor)

For every job the supervisor creates `<workspace>/.tmp/` and exports to the
worker process:

| Variable | Value |
|---|---|
| `TMP`, `TEMP`, `TMPDIR` | `<workspace>/.tmp` |
| `npm_config_cache` | `<workspace>/.tmp/npm-cache` |
| `PIP_CACHE_DIR` | `<workspace>/.tmp/pip-cache` |
| `UV_CACHE_DIR` | `<workspace>/.tmp/uv-cache` |
| `PYTHONPYCACHEPREFIX` | `<workspace>/.tmp/pycache` |
| `PIP_DEFAULT_TIMEOUT`, `PIP_RETRIES` | `120`, `5` |
| `UV_HTTP_TIMEOUT` | `120` |

`.tmp/` is gitignored (root `.gitignore`). Use it for `tempfile`, `pip install
--target .tmp/x ...`, `npx`, and scratch outputs; never write to the ambient
`%LOCALAPPDATA%\Temp` (denied under `read-only`, unlabelled under
`workspace-write`). `tempfile.mkdtemp()` works because `TMP` now points into the
workspace; inside a confined pwsh it points at the sandbox's private temp (also
writable).

Two sandbox facts drive the rest of the setup:

- The supervisor prepends `plugins/dsh-worker/worker_bootstrap` to the worker's
  `PYTHONPATH` and sets `DSH_WORKER_SANDBOXED=1` only for file-sandboxed jobs
  (`read-only`/`workspace-write`; never `danger-full-access`). Its
  `sitecustomize` drops Python 3.14's explicit `0o700` DACL when creating temp
  directories only when that marker is present: under the write-restricted
  token that DACL cuts off the inherited workspace capability, so
  `tempfile.mkdtemp()` could create a directory but not write inside it
  (`python -S`` bypasses this, and an ordinary Python process is never patched).
- `DSH_WORKER_PROGRESS_NOTES` points at `<workspace>/.tmp/PROGRESS_NOTES.md`,
  not the job directory (outside the sandbox). Digests read the new path first
  and fall back to the legacy `<job_dir>/PROGRESS_NOTES.md`.

`.tmp/` is also the supervisor's request channel (below). The worker can write
there under `workspace-write`.

## 3. Write scopes (`start_worker(write_scope=...)`)

| `write_scope` | dsh mode used | Confirmation | Extra authority |
|---|---|---|---|
| `workspace` (default) | the requested `permission` | — | workspace + `.tmp` only |
| `data` | forced `danger-full-access` | `confirm_data_write=true` + `writes=[...]` + `approved_by` text | `REALITY_DATA_ROOT` (`reality_engine/data`) and `D:\RealityEngine`; the supervisor holds `db:<file>` locks for each entry in `writes=[...]` |
| `full` | forced `danger-full-access` | `confirm_full_access=true` (Shivam approves first) + `approved_by` text | no file restriction |

**dsh 0.2.1 makes `data` == `full` access at the OS level.** Because the dsh
sandbox has one writable root per session and no extra-roots setting, a `data`
job runs the same `danger-full-access` mode as a `full` job: nothing at the OS
level stops it writing any file. The difference is process policy, not
enforcement — the brief's write roots, the named `db:<file>` locks and the human
approval. Treat `write_scope='data'` as full access that happens to be briefed
to touch only the named DBs.

`writes=[...]` is required for `data`: it accepts bare file names with or
without a `db:` prefix (`["equity_intelligence.db"]`), and a `data` job with an
empty list is refused with `writes_required` (it would hold no lock and could
write every DB). A non-`data` job that passes `writes` is refused with
`writes_requires_data_scope`. `approved_by` records who approved a `data`/`full`
job in `job.json`, `status.json` and `worker_status`; `confirm_*` is only the
caller's own flag, so the approval text is the audit trail. The manager writes a
start-window reservation for each named lock before it spawns the supervisor
(the supervisor removes it after taking the real OS lock), so a simultaneous
second start is refused with `resource_busy` before anything is launched.

`write_scope` is recorded in `job.json`, `status.json`, every progress digest,
`worker_status` and `list_workers`. `worker_status` prefers `status.json`: the
job record sits in a directory a worker could reach when its workspace is the
main checkout, so a hand-edited `job.json` scope does not change the reported
scope (and never changed the launch decision).

### The main checkout root is special

A **mutating** worker whose workspace is the main checkout root needs
`confirm_repo_root_write=true`; without it the start is refused with
`repo_root_write_requires_confirmation` before anything runs. Read-only workers
and worktree workers do not need the flag. The reason is plain: the main
checkout contains code that later runs *outside* the sandbox — the context-pack
builder (`reality_engine/scripts/build_worker_context.py`), the plugin's
`supervisor.py`, `.git/config` and other jobs' records. A worker that can rewrite
any of those can make the next supervisord/manager start execute its code. The
flag is an explicit statement that Shivam approved a worker which may rewrite
the repository root; it is recorded in `job.json`, `status.json`,
`worker_status` and `list_workers` next to `approved_by`. While such a worker
holds the repo-root lock, a new start does **not** regenerate
`tasks/worker_context/CONTEXT.md` (the stale pack is attached with a warning),
because the builder is worker-writable at that moment.

Never start a `data` job unless the brief is approved to write there. Never use
`full` without Shivam's explicit go-ahead.

## 4. Committing from a worktree job

The worktree index/objects live in the main checkout's
`.git/worktrees/<id>`, outside the sandbox's writable root, so `git commit`
inside the job is denied. Supported path:

1. The worker writes `<workspace>/.tmp/commit.request.json` with
   `{"message": "feat: ..."}` (its own `write` tool).
2. The supervisor (unconfined) runs the commit on the next ~2 s poll, appends
   the result to `status.worker_commits` (last 50 only), and writes
   `<workspace>/.tmp/commit.result.json` (`{"ok": true, "commit": {...}}`).
3. Works for a job-created worktree **and** for a workspace pointed at an
   existing worktree. Direct `git add`/`git commit` inside the job cannot work
   in either case: the index/refs live under `<main>/.git/worktrees/<id>`,
   outside the writable root, so use the request file. The supervisor's
   end-of-run auto-commit still runs and creates no second commit when the tree
   is clean.

The commit never trusts the worktree's `.git`. When the job starts, the manager
(outside the sandbox) records the real `git_dir`, `common_dir`, `toplevel`,
`head_ref` and `branch` in `job.json` (`job["git"]`). The supervisor then runs:

```
git --git-dir=<stored git_dir> --work-tree=<stored toplevel> \
    --attr-source=4b825dc642cb6eb9a060e54bf8d69288fbee4904 \
    -c core.hooksPath=NUL -c core.fsmonitor=false \
    -c core.sshCommand= -c diff.external= \
    -c core.attributesFile=NUL -c commit.gpgSign=false \
    -c gpg.program= -c core.editor= -c sequence.editor= -c core.pager= \
    add -A                      # then
    commit --no-verify -m ...   # only on refs/heads/dsh/...
```

with `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=NUL`,
`GIT_TERMINAL_PROMPT=0` and `GIT_ATTR_SOURCE=<empty tree>`. The empty-tree
attribute source means no in-tree `.gitattributes` can select a
`filter=`/`diff=`/`merge=` driver; `<git_dir>/info/attributes` cannot be
redirected that way, so a commit is refused (`git_attributes_driver_refused`)
when it names a driver. A clean filter or `gpg.program` planted in repo config
therefore never runs (pinned by tests).

Before `git add -A`, every path in `git status --porcelain -z` is checked with
`os.lstat`; a symlink or Windows reparse point (junction) at the path or any of
its ancestors refuses the commit (`reparse_point_in_workspace`) instead of
staging data from outside the workspace.

The post-run snapshot is taken through the same stored identity and the same
hardened runner — never `git -C <workspace>`: a rewritten `.git` means **no git
process runs** and `artifacts` reports `final_snapshot_unavailable` (the
snapshot reason is `git_dir_tampered`). Job records with no stored identity
(older records) are treated the same way: no snapshot. The start-of-run
baseline in `baseline.json` uses the identity too, so `artifacts.paths` still
works for normal worktree and main-checkout jobs.

It refuses when the stored common dir is not `<repo>/.git`, when the stored git
dir is the main checkout's own `.git` (the main checkout is never a worker
commit target), when `<workspace>/.git` no longer points at the stored git dir
(worker-owned fake gitdir / redirect to another repository), or when HEAD is not
a `refs/heads/dsh/...` branch (or the recorded branch). So a worker that
rewrites `.git` cannot run its own `pre-commit` hook or commit into another
repository, and the request file can never supply git `-c` options.

## 5. Detached long-running processes (`write_scope` data/full only)

A child of a confined shell dies with it, and the supervisor holds a
`KILL_ON_JOB_CLOSE` job object, so a normal background child dies too. The
supported escape is WMI: the supervisor runs `Invoke-CimMethod Win32_Process
Create`, so WmiPrvSE — not the worker or the supervisor — is the parent.

Worker protocol: write `<workspace>/.tmp/launch.request.json`:

```json
{
  "cmd": "python -m reality_engine.scripts.some_job --flag",
  "log": ".tmp/some-job.log",
  "cwd": ".",
  "env": {"REALITY_DATA_ROOT": "C:/Users/warri/Downloads/Info_Diffusion_Model/reality_engine/data"}
}
```

- `cmd` is a string or an argv list; it runs through `cmd.exe /c` (a `.cmd`
  wrapper is generated under `.tmp`).
- `log` and `cwd` must resolve inside `.tmp`, the workspace, `REALITY_DATA_ROOT`
  or `D:\RealityEngine`; the default log is `.tmp/detached-<ts>.log`.
- Optional `env` is written as `set` lines into the wrapper (WMI-created
  processes do not inherit the worker's environment — Winmgmt's environment is
  the parent — so pass absolute interpreter paths or an explicit `PATH`).
- The supervisor writes `.tmp/launch.result.json` with `ok`, `pid`, `log`, and
  records `pid`/`command`/`log` in `status.detached` (the job record view).
- Refused unless `write_scope` is `data` or `full`
  (`launch_detached_requires_write_scope_data_or_full`).

## 5a. Testing the sandbox from inside a sandbox

A nested sandbox cannot be created from an already-confined token: *** runner's
`SetNamedSecurityInfoW` fails with Win32 5 (our token has no `WRITE_DAC`) and
`CreateRestrictedToken` fails with Win32 87 when the caller is already
write-restricted. Run end-to-end sandbox demos from Claude's unconfined shell,
from a supervisor-launched worker, or (as Task 03 did) exercise the same
workspace-write token that the session already holds. The Task 03 probe is
`tasks/worker_context/sandbox_probe.py` (its docstring has the exact command).

## 6. Dependencies and per-task venvs

- `requirements-worker.txt` (repo root): pymupdf, pyyaml, requests, numpy,
  pandas, duckdb, openpyxl, xlrd. All have a cp314/abi3 Windows wheel
  (`setup_worker_env.py --dry-run` prints the exact filename). `rapidocr` is
  excluded: its onnxruntime backend has no cp314 wheel. No pytest (unittest).
- `python reality_engine/scripts/setup_worker_env.py` installs missing packages
  into the user site with `--timeout 120 --retries 5`; it is idempotent and
  prints what changed. `--dry-run` installs nothing.
- Optional per-task venv: `python -m venv .venv-<task>` (gitignored), then
  `.venv-<task>\Scripts\python -m pip install -r requirements-worker.txt`. Use
  one only when a task needs pins that conflict with the shared site.
- `tasks/worker_context/pip.ini` and `uv.toml` are the same timeouts as a config
  file for interactive use; workers already inherit them through env vars.

## 7. Files Claude must install outside the worker sandbox

The worker cannot write `~/.dsh`, `%APPDATA%`, or the main checkout's `.git`.
Claude (unconfined) installs these after review; exact commands are in the Task
03 report and in `tasks/dsh_profiles/README.md`:

- `tasks/dsh_profiles/headless.cordis.patch.yml` → `~/.dsh/profiles/headless/cordis.patch.yml`
- `tasks/dsh_profiles/web.cordis.patch.yml` → `~/.dsh/profiles/web/cordis.patch.yml`
- `tasks/worker_context/pip.ini` → `%APPDATA%\pip\pip.ini`
- `tasks/worker_context/uv.toml` → `%APPDATA%\uv\uv.toml`

Back up each existing file first. The profile change adds the 10-minute pwsh cap
and turns `promoteOnTimeout` off, so a command that reaches the cap is killed
instead of being promoted to a background job.

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
