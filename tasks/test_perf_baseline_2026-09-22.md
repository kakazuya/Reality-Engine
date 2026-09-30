# Test-suite speed baseline — 2026-09-22

Test-infra task: 690-test suite to under ~60s wall on the 12-thread i5, byte-identical results.
Production code untouched; test-infra only. `pytest` 9.1.1 + `pytest-xdist` 3.8.0 installed
dev-only (NOT pinned in any manifest — `requirements.txt` intentionally unedited).

## Grounding (verified before editing)

- `FinancialOCREngine` (`reality_engine/processing/ocr_engine.py`): `__init__` stores flags
  only; the DirectML session builds in `_ensure_engine()`, triggered by the lazy
  `engine` / `provider` properties. Failure degrades to `engine=None`, `provider="NONE"`.
- `OnnxEmbedder` (`reality_engine/ingestion/onnx_embedder.py`): `__init__` stores config only;
  `_ensure()` (DML-or-CPU `ort.InferenceSession`, sequential mode, internal lock) runs on
  first `embed` call. Missing deps/files → `available=False`, callers keep hash fallback.
  Process singleton: `onnx_embedder`.
- Per-test construction grep (`reality_engine/tests`): only `test_macro_ingest.py`
  (3× `PDFIngestor(db=mgr, vector_store=_StubVectorStore())`, lines 87/134/170) and
  `test_document_industry_tag.py` (2× `PDFIngestor(db=mgr, vector_store=StubVectorStore())`,
  lines 66/98) construct engines per-test — via `PDFIngestor.__init__`'s
  `ocr_engine or FinancialOCREngine()` default. `test_filing_ingestion.py` constructs
  NO engine per-test (only `OfficialFilingClient`/`CorporateActionsClient`/…; grep negative),
  so it is left alone. `test_news_vision.py` defines a local `_OCR` stub (not the real
  engine — left alone). `test_onnx_embedder.py` constructs `OnnxEmbedder` per-test
  deliberately (fail-closed/missing-files semantics — migrating it would change what the
  tests prove; left alone, recorded).
- No `conftest.py` existed anywhere under `reality_engine/` (glob negative) — new file is ours.
- Sibling-owned files (`eod_corrector.py`, `move_attributor.py`, `orchestrator.py`,
  `test_eod_corrector.py`, `test_move_attribution.py`, `test_action_thesis.py`) untouched.

## BEFORE — first-half shard, serial

Command (same module list as the parent's shard, `action_thesis` through `news_explainer`,
36 modules, alphabetical):

```text
pytest test_action_thesis.py test_agent_and_reporting.py test_attention_ranker.py
  test_backfill_call_rows.py test_bootstrap.py test_bse_backfill.py
  test_bse_fundamentals_client.py test_catchup_scheduler.py test_cli_and_dashboard.py
  test_continuous_loop.py test_data_audit_holiday.py test_deals_client.py
  test_derived_substrate.py test_distillation_macro.py test_distilled_expansion.py
  test_document_industry_tag.py test_ensemble_ranker.py test_ensemble_weighted.py
  test_eod_corrector.py test_event_graph.py test_filing_ingestion.py
  test_financial_denominator.py test_forecast_capacity.py test_horizon_excess.py
  test_index_backfill.py test_intel_search.py test_lifecycle_pruning.py
  test_llm_lens_client.py test_macro_ingest.py test_macro_pdf_fetcher.py
  test_master_bse_admission.py test_master_upsert.py test_merge_lane_db.py
  test_moat_backfill.py test_moe_all_universe.py test_move_attribution.py
  test_news_announcements.py test_news_explainer.py --durations=20 -q
```

Result: **386 passed, 4 subtests passed in 136.78s** (process wall 138.95s).
Full-suite collect: 736 tests.

### Slowest 20 (before)

| # | Time | Test |
|---|------|------|
| 1 | 21.05s | test_bootstrap.py::TestBootstrapWorkflow::test_04_bootstrap_idempotency |
| 2 | 15.72s | test_bootstrap.py::TestBootstrapWorkflow::test_03_bootstrap_cli_execution |
| 3 | 12.55s | test_bootstrap.py::TestBootstrapWorkflow::test_02_bootstrap_manager_clean_database |
| 4 | 10.87s | test_bootstrap.py::TestBootstrapWorkflow::test_05_sample_only_fast_bootstrap |
| 5 | 5.20s | test_action_thesis.py::TestCliVerbsParse::test_full_parser_registers_verbs |
| 6 | 3.78s | test_moe_all_universe.py::TestMoeAllUniverse::test_rerun_is_idempotent |
| 7 | 2.74s | test_cli_and_dashboard.py::TestCLIAndDashboard::test_02_cli_seed_ontologies |
| 8 | 2.09s | test_bse_backfill.py::TestBseBackfill::test_10_legacy_zip_fetch_parse_and_join |
| 9 | 1.68s | test_moe_all_universe.py::TestMoeAllUniverse::test_cli_parser_run_moe_eod_help |
| 10 | 1.65s | test_moe_all_universe.py::TestMoeAllUniverse::test_cli_parser_seed_peers_help |
| 11 | 1.50s | test_moe_all_universe.py::TestMoeAllUniverse::test_20_rows_per_symbol_5_cohorts_4_families |
| 12 | 1.49s | test_moe_all_universe.py::TestMoeAllUniverse::test_weights_sum_to_one_with_floor_values |
| 13 | 1.41s | test_moe_all_universe.py::TestMoeAllUniverse::test_symbol_keyed_compatibility |
| 14 | 1.40s | test_moe_all_universe.py::TestMoeAllUniverse::test_full_universe_creates_60_rows |
| 15 | 1.39s | test_action_thesis.py::TestThesisAttach::test_attach_with_seeded_row |
| 16 | 1.38s | test_document_industry_tag.py::TestDocumentIndustryTag::test_chunk_industry_derived_from_company_join |
| 17 | 1.12s | test_moat_backfill.py::TestMoatBackfill::test_06_backfill_top_n_seeds_top20 |
| 18 | 1.04s | test_filing_ingestion.py::TestCorporateActionsClient::test_fetch_range_auto_sliced |
| 19 | 1.02s | test_moe_all_universe.py::TestMoeAllUniverse::test_limit_slices_deterministically |
| 20 | 0.88s | test_cli_and_dashboard.py::TestCLIAndDashboard::test_10_cli_search_concall |

Read: bootstrap DB setup dominates (~60s alone); per-test OCR DirectML init (~0.8s each,
one `OCR engine initialized with DirectML` log line per PDFIngestor test) is below the
top-20 but multiplies across the full suite — the sharing target. Temp-DB setup cost is
a measured follow-up candidate (memory-DB conversion explicitly OUT of scope).

## AFTER — full suite under xdist

Command: `pytest -n 12 reality_engine/tests -q --tb=short -p no:warnings --durations=20`

Result: **738 passed, 27 subtests passed in 199.65s** (process wall 200.54s) — GREEN,
zero failures/errors. The 738 = 736 collected before this task plus the 2 new hermetic
`test_shared_engines.py` guard tests added by this task; every pre-existing test passes
under pytest exactly as in the unittest baseline logs (no FAIL/ERROR lines in the
`full_suite_verbose_2026-09-22.log` baseline; zero failures here) — no deviation to
report or paper over.

Target check: **NOT MET — 199.65s vs the ~60s goal**, reported honestly. The serial
first-half shard (136.78s for 386 tests) extrapolated to ~260s for the full 738, so
xdist is only ~1.3× faster than serial: the suite is NOT parallelizable in its
current shape. The suspected culprit — DirectML session contention (DML sessions are
documented sequential-only; 12 workers hammer one GPU) plus lock-held skew — is
confirmed by the AFTER top-20: the same tests that were 1–21s serially now take
20–73s under xdist (e.g. `test_bootstrap clean_database` 12.55s → 31.93s,
`test_attach_with_seeded_row` 1.39s → 52.59s).

### Slowest 20 (after, under `-n 12`)

| # | Time | Test |
|---|------|------|
| 1 | 72.91s | test_v2_ingestion_adapters.py::TestV2IngestionAdapters::test_11_financially_free_nse_index_breadth_fallback |
| 2 | 59.55s | test_telegram_hardening.py::TestTelegramHardening::test_04_thread_topic_fallback_and_extraction |
| 3 | 57.75s | test_polars_batch.py::PolarsBatchTest::test_pandas_in_pandas_out |
| 4 | 52.59s | test_action_thesis.py::TestThesisAttach::test_attach_with_seeded_row |
| 5 | 52.46s | test_agent_and_reporting.py::TestAgentAndReporting::test_06_nullable_policy_no_template_GMRAIRPORT_regression |
| 6 | 51.98s | test_action_thesis.py::TestCliVerbsParse::test_run_calibration_stub_prints_json |
| 7 | 51.46s | test_telegram_hardening.py::TestTelegramHardening::test_07_sanitize_and_database_persistence |
| 8 | 31.93s | test_bootstrap.py::TestBootstrapWorkflow::test_02_bootstrap_manager_clean_database |
| 9 | 29.65s | test_telegram_hardening.py::TestTelegramHardening::test_05_media_handling_image_bytes_and_missing_path |
| 10 | 29.46s | test_bootstrap.py::TestBootstrapWorkflow::test_04_bootstrap_idempotency |
| 11 | 26.59s | test_action_thesis.py::TestCliVerbsParse::test_full_parser_registers_verbs |
| 12 | 25.96s | test_telegram_hardening.py::TestTelegramHardening::test_10_ocr_and_inbox_integration_graceful_no_file |
| 13 | 24.97s | test_v2_ingestion_adapters.py::TestV2IngestionAdapters::test_04_telegram_text_message_processing |
| 14 | 22.15s | test_bootstrap.py::TestBootstrapWorkflow::test_03_bootstrap_cli_execution |
| 15 | 22.11s | test_moe_all_universe.py::TestMoeAllUniverse::test_rerun_is_idempotent |
| 16 | 21.00s | test_v2_ingestion_adapters.py::TestV2IngestionAdapters::test_05_telegram_image_message_processing |
| 17 | 19.42s | test_moe_all_universe.py::TestMoeAllUniverse::test_full_universe_creates_60_rows |
| 18 | 17.95s | test_validation_harness.py::TestLensCalibration::test_fit_does_not_mutate_rankings_but_apply_does |
| 19 | 11.07s | test_bootstrap.py::TestBootstrapWorkflow::test_05_sample_only_fast_bootstrap |
| 20 | 9.31s | test_cli_and_dashboard.py::TestCLIAndDashboard::test_02_cli_seed_ontologies |

## Remaining top offender + measured follow-ups

- Remaining top offender: `test_v2_ingestion_adapters.py::test_11_…_fallback` at
  72.91s under xdist — but only 15.83s run alone serially (verified), so the cost is
  contention, not the test itself. Same for telegram_hardening / polars_batch /
  action_thesis entries: all inflate 3–30× under 12 workers sharing one GPU.
- The sibling-owned `test_action_thesis.py` rows are named here as data only;
  that file was NOT touched (sibling-owned).
- Measured follow-ups (out of scope, recorded only): (1) real fix is a serial-fast
  suite, not more workers — profile the serial top-20 (bootstrap DB setup ~60s,
  parser registration ~5s, moe universe seconds each) before touching parallelism;
  (2) temp-DB setup did NOT appear as a top offender in either durations table, so
  memory-DB conversion stays a no-evidence option, not a recommendation; (3) the
  shared-OCR migration in this task removed ~4 redundant DirectML builds
  (`test_macro_ingest.py` 3 sites + `test_document_industry_tag.py` 2 sites → one
  shared instance per worker) — correct but small; engine sharing was never the
  dominant cost.

## Migration record

- Migrated (safe, grep-verified): `test_macro_ingest.py` (3 `PDFIngestor(...)` sites
  → `ocr_engine=get_shared_ocr_engine()`), `test_document_industry_tag.py` (2 sites →
  same). Scoped proof: 7 migrated tests + 2 new guard tests, 9 passed.
- Deliberately left: `test_filing_ingestion.py` (grep-verified: constructs NO engine
  per-test — nothing to migrate), `test_news_vision.py` (local `_OCR` stub, not the
  real engine), `test_onnx_embedder.py` (per-test `OnnxEmbedder` construction is the
  fail-closed contract under test — sharing it would change what is proven).
- `pytest` + `pytest-xdist` installed dev-only (pytest 9.1.1, xdist 3.8.0); no manifest
  edited. Note for the parent: the 690-test/60s target needs the serial-profile
  follow-up above, not this task's fixture layer.
