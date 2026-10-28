# Progress — download filters (NSE buckets + concall widen/rescue), 2026-10-28

- 2026-10-28: read pack + target files; drafted bucket classifier from `tasks/dsh_tasks/nse_buckets_draft.py`.
- 2026-10-28: `bucket()`/`record_bucket()` + `--download-buckets` in nse_announcements.py; bucket stored in every JSONL row; fixed a shadowed `key` in `run()` that broke the resume manifest. Classifier tuned on the 9,632-row pilot (1,398 transcript / 3,436 material / 4,078 procedural / 720 unclear).
- 2026-10-28: hand-checked 40 random rows per bucket: transcript 40/40, material 40/40, procedural 40/40 (0 material leaks), unclear 2/40 material leaks (business-update wording, SEBI order).
- 2026-10-28: concall_refetch.py `--transcript-word` (widen: 1,594 of 2,301 fresh) and `--rescue-file` (214 rows; dry-run 214 sampled, 14 probe-reused, 13 transcripts). Offline tests added; next: final test run + report.

# Progress — answerability benchmark (tasks/answer_bench), 2026-10-28

- 2026-10-28: `build_sample.py` -> `SAMPLE.jsonl` 150 rows (30 regressions, 30 reddit200, 90 stratified). Coverage: every family >=3, every entity level >=5 except `price band` (1 case exists in the whole bank).
- 2026-10-28: `run_bench.py` probes each case through the same functions the reality-data MCP server exposes (toolbelt pattern), hop-by-hop, <=8 calls/case, 15 s per-statement ceiling. Next: full 150-case run -> RESULTS.jsonl -> REPORT.md roll-up.
- 2026-10-28 DONE: 150-case run, 514 tool calls, 273 s. ANSWERED 20/150 (13.3%), regressions 8/30 (26.7%); PARTIAL 76, BLOCKED_SCHEMA 24, BLOCKED_TOOL 17, NOT_IN_DATA 13, WRONG 0. `REPORT.md` has the family/level/bank tables, blocker table, top-15 additions, PIT (1 hard leak: `doc_page` returns a post-as_of page; 81 cases exposed because facts/docs/doc_find have no as_of), slow tools (`search_docs` 33.8 s, `facts`+period 15 s timeouts). `check.py` passes the acceptance test.
- Caveat to carry forward: ANSWERED is conservative - the same data under looser lexical matching gave 47/150; 5 calibration runs 47->36->26->22->20. Anti-benchmark bias check needs a second opinion on ~20 ANSWERED rows.
- 2026-10-28 FINAL: hand audit (`recheck.py`) read all 20 probe-ANSWERED rows against their questions and downgraded 13 that answered part of a multi-part ask -> **ANSWERED 7/150 (4.7%), regressions 4/30 (13.3%)**, ANSWERED-or-PARTIAL 95/150 (63.3%), PARTIAL 88, BLOCKED_SCHEMA 25, BLOCKED_TOOL 17, NOT_IN_DATA 13, WRONG 0. 514 tool calls, 273 s. Blocker order: G11 28, G6 20, NG16 18, G10 14, G12 14, NG13 10, G3 9. `check.py` and the brief's test command both pass.
