# Task — query speed: every master-bank question in under 10 s, p95 ≤ 5 s, with no LLM in the loop

## Goal
Shivam wants answers in about 10 s. The latest benchmark (`tasks/answer_bench/RESULTS_v1.jsonl`, 150 cases) took 341 s in total: mean 2.3 s, p50 1.3 s, p95 6.9 s, max 15.6 s. 24 cases are over 5 s and 2 are over 10 s (MB0011, 8 planner hops; MB0201).

Answering is deterministic Python/SQL: router → planners → compute. Keep it that way. **Targets: p95 ≤ 5 s and max ≤ 10 s, with the grades unchanged or better.**

## Do
1. **Profile** every hop on the 150 cases: time per planner, per SQL statement, and per search call. Write the top 20 slow statements with their `EXPLAIN QUERY PLAN`.
2. **Run sub-questions and independent hops in parallel:** a thread pool in `answer.py`, using read-only connections per thread (`connect_ro`). Keep the output order deterministic.
3. **Share work within a question:** a per-question cache keyed on (planner, entity, period), because sub-questions often re-resolve the same company, prices or filings. Keep the warm SQLite connections, so nothing reconnects per hop.
4. **EVIDENCE:** prefer chunks_v3, `REALITY_CHUNKS_V3=D:\RealityEngine\pilot\chunks_v3_pilot.db`, wherever it covers the ISIN. Where it doesn't, bound the `document_chunks` fallback with an ISIN + date pre-filter, a LIMIT, and no LIKE over the full table.
5. **Indexes:** apply `tasks/arch_v3/INDEX_MIGRATION_V0.sql` (plus the two the architecture flagged: `corporate_documents(isin, publication_date)` and `ann(symbol, DissemDT)`) to **copies** of the DBs under `.tmp/` and measure the gain there. **Never write the live DBs.** Produce the exact migration script for the controller to run.
6. **Screens** (SCREEN/RIPPLE market-wide): read the pilot whole-market tables (`D:\RealityEngine\pilot\market_state_pilot.db`, the indexed `company_state_daily`) or the DuckDB snapshot, never row loops in Python.
7. Re-run the 150 cases with the strict grader (`tasks/answer_bench/grade_v1.py`). Report the latency distribution before/after, and confirm the grades didn't drop.

## Rules
- Read-only on live DBs; migrations go on copies in `.tmp/` only. Write only in this worktree. No network, no paid embeddings, no LLM calls, no commits.

## Acceptance checks
1. p95 ≤ 5 s and max ≤ 10 s on the 150 cases, with strict ANSWERED ≥ 13 and WRONG = 0.
2. `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` passes.
3. `tasks/answer_bench/SPEED_REPORT.md`: the profile, the fixes, and the before/after table, plus the migration SQL for the controller.

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

## Report
Give:
- the latency before → after (mean, p50, p95, max, and the count over 5 s and over 10 s);
- the grades before → after;
- the migration SQL, with its measured gain;
- your tool-call count.
