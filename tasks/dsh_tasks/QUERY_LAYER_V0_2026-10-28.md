# Task — build query layer v0 (router + planners) on held data and lift the benchmark from 7/150

## Goal
The reviewer cross-checked two outputs:
- `tasks/arch_v3/CASE_MAP.jsonl` (design) marks 61 of the 150 benchmark cases `answerable_now`;
- `tasks/answer_bench/RESULTS.jsonl` (measured with today's tools) answers only **5 of those 61** end to end. Another 38 are PARTIAL, and 17 are BLOCKED_TOOL/SCHEMA.

So the data is mostly there; what's missing is the query layer. That means multi-hop chaining, arithmetic (CAGR, ratios, deltas, windows), PIT `as_of` on every tool, and speed. Build v0 of the layer designed in `tasks/arch_v3/QUERY_LAYER.md` and prove it on the benchmark.

## Do
1. **Package** `reality_engine/query/`:
   - `router.py`: deterministic, routing on `(source_bank, archetype, family, entity_level)` as QUERY_LAYER.md says.
   - `planners/`: resolve, FACTS, SERIES, SCREEN, EVENT, EVIDENCE, COMPARE, RIPPLE. Each returns rows with provenance (db.table.key or doc_id+page, known_at) and an explicit `nid_reason` when empty.
   - `compute.py`: CAGR, growth, margin, ratio, window return, max/min, rank, peer percentile. Pure functions with tests.
   - `answer.py`: assembles the hops and computed values into a structured answer, plus the NOT-IN-DATA wording from QUERY_LAYER.md.
2. **PIT everywhere.** Every planner takes `as_of` and pushes `known_at <= as_of` (or the per-table PIT key from CASE_MAP `pit_key`) into the SQL.
   - Fix the leak the bench found: `doc_page` returned a 2026-10-24 document for an as_of of 2026-10-19 (MB0026).
   - Add `as_of` to the `reality-data` `facts`/`docs`/`doc_find` tools in `plugins/reality-data/server/`, backward compatible. Add tests.
3. **Speed:** `facts` with a period took 15.5 s and `search_docs` peaked at 33.8 s in the bench. Find the cause (EXPLAIN QUERY PLAN), fix it in code, and list any index that needs a DB migration (don't run migrations; give the exact SQL). Target: every planner call < 2 s on today's DBs.
4. **Harness:** `tasks/answer_bench/run_v0.py` runs all 150 SAMPLE cases through the router. Grade them with the same rules and the same `recheck.py` strictness as the bench, so the numbers are comparable. Output `RESULTS_v0.jsonl` + `REPORT_v0.md`:
   - before/after by grade, family, level and bank;
   - the 30 regressions;
   - the remaining blockers, mapped to CASE_MAP statuses and gap ids;
   - a **CASE_MAP accuracy table**: status × grade. Where CASE_MAP says answerable_now but v0 can't answer, name the exact missing piece.
5. Use only held data. Don't build the new pilot tables; that is another worker's job. Where a planner needs one, return BLOCKED_SCHEMA with the table name.

## Rules
- Read-only DBs (`connect_ro`). No network, no paid embeddings. Write only in this worktree. No commits.
- Don't loosen grading to inflate numbers. A multi-part question answered on only one part is PARTIAL.

## Acceptance checks
1. `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` passes, with tests for the router, every planner on fixtures, compute, and PIT (a document after as_of is never returned).
2. RESULTS_v0.jsonl has 150 rows, and REPORT_v0.md has the before/after and the CASE_MAP accuracy table.
3. Zero PIT violations in v0.

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

## Report
Give:
- ANSWERED and PARTIAL, before → after (overall and for the regressions);
- the CASE_MAP accuracy table;
- the top 10 remaining blockers, each with the table/tool that fixes it;
- the speed fixes, plus the migration SQL;
- your tool-call count.
