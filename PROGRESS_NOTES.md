# Progress — download filters (NSE buckets + concall widen/rescue), 2026-10-28

- 2026-10-28: read pack + target files; drafted bucket classifier from `tasks/dsh_tasks/nse_buckets_draft.py`.
- 2026-10-28: `bucket()`/`record_bucket()` + `--download-buckets` in nse_announcements.py; bucket stored in every JSONL row; fixed a shadowed `key` in `run()` that broke the resume manifest. Classifier tuned on the 9,632-row pilot (1,398 transcript / 3,436 material / 4,078 procedural / 720 unclear).
- 2026-10-28: hand-checked 40 random rows per bucket: transcript 40/40, material 40/40, procedural 40/40 (0 material leaks), unclear 2/40 material leaks (business-update wording, SEBI order).
- 2026-10-28: concall_refetch.py `--transcript-word` (widen: 1,594 of 2,301 fresh) and `--rescue-file` (214 rows; dry-run 214 sampled, 14 probe-reused, 13 transcripts). Offline tests added; next: final test run + report.
- 2026-10-28 (arch_v3 worker): read pack + reviewer draft + overhaul + gap rollup + ripple schema requirements; built CASE_MAP.jsonl (1030 rows, 0 unverified columns), SCHEMA_V3.sql (72 tables, 2 views, 40 indexes, parses), QUERY_LAYER.md, SPEED_PLAN.md (26 live + 5 duckdb + 11 prototype timings), COVERAGE.md, PILOT_SPEC.md (30-ISIN pilot, 362 cases). Next: reviewer sampling; open: 46 U-DOC originals + 62 commodity-series fetches block the 95% gate.
