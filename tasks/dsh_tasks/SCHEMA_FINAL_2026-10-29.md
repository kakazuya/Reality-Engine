# Task — the final database design: one schema where every master-bank question is answerable or NOT IN DATA with a reason

## Goal
Golden-rule step 3 (AGENTS.md): the schema must be designed so that every question in the approved master bank (1,073 cases, `tasks/master_bank/`) can be answered from data we hold. Every gap is closed by a table or field, or marked NOT IN DATA with a reason. Shivam needs this **complete by 13:00 IST today (29 Oct)**.

The pieces exist but are scattered. Consolidate them into ONE authoritative design:
- `tasks/arch_v3/SCHEMA_V3.sql`, `CASE_MAP.jsonl`, `COVERAGE.md`, `QUERY_LAYER.md`, `PILOT_SPEC.md`, `INDEX_MIGRATION_V0.sql`, `SPEED_PLAN.md`;
- `tasks/arch_v3_chunks/INDEX_SPEC.md`;
- `tasks/RIPPLE_SCHEMA_REQUIREMENTS_2026-10-28.md`, `tasks/LABELS_TAGGING_PLAN_2026-10-27.md`, `tasks/QUERY_TEMPLATES_2026-10-27.md`, `tasks/ARCHITECTURE_OVERHAUL_2026-10-27.md`;
- the tables the pilot actually built. Read their real DDL from the SSD copies, read-only through `connect_ro`, under `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\pilot\`:
  - `pilot60/market_state_pilot.db`, `pilot60/facts_pilot.db`, `pilot60/chunks_v3_pilot.db`, `pilot60/results_notes_chunks.db`;
  - `macro_all.db` and `results_notes.db`.

  Never read DBs from D: (HDD).
- the live stores, schema only: `reality_engine/data/*.db` via `connect_ro` + `sqlite_master`, and the reality-data `catalog()`.
- the gaps reports: `tasks/pilot60/REPORT.md` (top-15 gaps) and `tasks/macro_pilot/REPORT_ALL.md` (open problems). Use `tasks/answer_bench/GATE_RUN_2026-10-29.md` too, if it exists when you start; another worker is writing it.

## Do
1. **Inventory.** List every table that exists (live + pilot) with its row count, key, point-in-time columns (`known_at`, `pit_conf`, `as_of`/`valid_from`/`valid_to`) and indexes. Mark each table live, pilot-built or designed-only (in SCHEMA_V3 but not built).
2. **Map the bank to tables.** For each of the 1,073 cases (use `CASE_MAP.jsonl` and the bank's family/template fields), give the tables and fields each hop needs. Then classify the case:
   - (a) answerable from built tables;
   - (b) answerable once a designed table is built (name it, with its source data and build method);
   - (c) NOT IN DATA, with a specific reason: consensus estimates by Shivam's ruling, intraday prices not needed, paid feeds declined, data that truly doesn't exist, and so on.

   Report counts by family and level.
3. **Close every (b) gap** with an exact DDL: columns, types, keys, PIT columns, indexes and the planner that reads it. Also give the source (which raw data, already held?) and a build-cost estimate. Reuse a table wherever possible, so you don't proliferate tables.
4. **Write `tasks/SCHEMA_FINAL_2026-10-29.md`** with these sections:
   - §1 principles: ISIN anchor + ISIN-history map, PIT rules (known_at from the filing record, the 15:30 IST day-0 rule), SSD vs HDD placement, SQLite-per-domain + DuckDB snapshot + FTS5 + NumPy/FAISS;
   - §2 every table, grouped by domain, with DDL, keys, PIT and indexes;
   - §3 the bank coverage matrix: family × level → a/b/c counts, plus the full per-case list in an appendix JSONL `tasks/SCHEMA_FINAL_CASES_2026-10-29.jsonl`;
   - §4 the NOT IN DATA list with reasons;
   - §5 the build order for the remaining (b) tables, with estimated hours;
   - §6 open decisions for Shivam: embedding dimension, anything else genuinely his call.

   Also write `tasks/SCHEMA_FINAL_2026-10-29.sql`, a complete, runnable DDL.
5. **Validate the SQL**: apply it to an empty SQLite DB in `.tmp/` and make sure it runs clean. Also check that every table named in CASE_MAP or the planners (`reality_engine/query/planners/*.py`) exists in the final SQL or is explicitly retired.

## Rules
- Everything is read-only on data. Write only in this worktree. Use no paid models and make no commits.
- Be honest about classification. Put a case in (a) only if the built table actually holds the needed field for pilot companies (spot-check rows). Never call something NOT IN DATA just to make the numbers look good.

## Acceptance checks
- `python -c "import sqlite3;c=sqlite3.connect(':memory:');c.executescript(open('tasks/SCHEMA_FINAL_2026-10-29.sql',encoding='utf-8').read());print('ok')"` prints ok.
- `SCHEMA_FINAL_CASES_2026-10-29.jsonl` has exactly 1,073 rows, each with `case_id`, `class` (a/b/c), `tables`, and `reason` (required for c).
- `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` still passes; you shouldn't need any code change.

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

## Report
Give:
- the a/b/c counts overall and by family;
- the number of tables (live, pilot and new);
- the top 10 (b) tables, ranked by the cases they unblock;
- the NOT IN DATA reasons with counts;
- the open decisions;
- your tool-call count.
