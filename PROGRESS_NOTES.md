# Progress notes — query layer v1 (worktree 2026-10-28T175323Z)

- v1 implemented in `reality_engine/query/`: `decompose.py` (deterministic
  sub-question split from conjunctions + rubric steps, per-sub router chain,
  ranking-winner hand-off), `rerank.py` (BM25 + entity/metric/date features),
  `answer.py` (per-sub assembly, metric-family relevance filter, synonym table),
  `planners/facts.py` (named-document ±3d preference, newest-first, no fallback
  to an older document), `planners/evidence.py` (named-doc filter + rerank +
  doc metadata on rows), `router.py` (`named_document`, whole-word metric keys).
- Strict grader `tasks/answer_bench/grade_v1.py` + v1 runner `run_v1.py`; v1
  results in `RESULTS_v1.jsonl`, strict re-grade of both in
  `RESULTS_v0_strict.jsonl` / `RESULTS_v1_strict.jsonl`, report `REPORT_v1.md`.
- Final: strict v0 ANSWERED 6 / PARTIAL 101 / WRONG 16 / blocked 27;
  strict v1 ANSWERED 13 / PARTIAL 106 / WRONG 0 / blocked 31. 7 fixed cases.
- Tests: `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"`
  → 55 tests OK (24 new in `test_query_v1.py`).
- Done. Next: controller review/merge. No blockers.
