# Progress notes — query layer v0 + bench lift

Job dir: this worktree (DSH_WORKER_PROGRESS_NOTES was empty in the session env, so the
notes live at the worktree root; flagged in the final report).

- 2026-10-28 ~milestone 1 — read context pack, QUERY_LAYER.md, CASE_MAP/RESULTS; measured
  the 15.5 s `facts` miss (symbol fallback scanned 32.4M ar_facts rows) and the cold
  `search_docs` load. Added PIT `as_of` to `facts`/`docs`/`doc_page`/`doc_find` and fixed
  the `doc_page` leak. Next: query package + tests + harness.
- 2026-10-28 ~milestone 2 — `reality_engine/query/` built (router, 8 planners + expectations
  gate, compute, answer, ctx); `test_query_*` 31 tests pass; first full v0 run 150/150,
  0 PIT violations, ANSWERED 34. Found inflation in advice-template questions and junk
  facts from text-valued concall rows; added the expectations gate, numeric-only facts,
  promoter screen from `shp_index`, corpus EVIDENCE via `search_docs`, and stricter
  period/qualifier filters. Next: final full run + report.
- 2026-10-28 ~milestone 3 — final harness numbers: ANSWERED 17/150 (was 7), PARTIAL 106
  (was 88), BLOCKED_SCHEMA 17, BLOCKED_TOOL 9, NOT_IN_DATA 1 (MB0026, the PIT leak),
  0 PIT violations; 30 regressions ANSWERED 4 -> 7. Of the 61 CASE_MAP `answerable_now`
  cases: ANSWERED 5 -> 17. CASE_MAP status enforcement added (needs_new_fetch/table
  cannot grade ANSWERED). Speed: FACTS p95 0.7 s, SERIES 0.1 s, SCREEN 0.8 s,
  resolve 0.03 s; EVIDENCE p50 1.7 s / p95 5.6 s (LIKE passage scan + cold corpus
  index) remains the one planner over the 2 s target — chunks_v3 / the index migration
  in `tasks/arch_v3/INDEX_MIGRATION_V0.sql` is the fix. Done; no open blockers for the
  deliverable itself.
