# Task — design the query + data architecture that answers every master-bank question, quickly and point-in-time

## Objective
This is step 3 of the golden rule (AGENTS.md, top): a schema designed so that **every** master-bank question is answerable from data we hold, or is marked NOT IN DATA with a reason. It must also be **fast**: search p95 < 2 s, structured lookups < 300 ms.

Your output is the design that the pilot (step 4) gets built from. The reviewer (Claude) will test it hard, so every claim must be checkable.

## Inputs (read these first)
- `tasks/master_bank/MASTER_BANK.jsonl` + `MASTER_BANK.md`: 1,030 cases, each with family, entity_level, answer_kind, rubric and gaps.
- `tasks/master_bank/GAP_ROLLUP.md`: 58 gap clusters, with closable-from-held-data per gap.
- `tasks/QUERY_ARCHITECTURE_PILOT_PLAN_2026-10-28.md`: the reviewer's draft (router by answer_kind, 6 planners, schema-add ranking, chunking spec, pilot design). **Challenge it; don't copy it.** Say where it is wrong or thin.
- `tasks/ARCHITECTURE_OVERHAUL_2026-10-27.md`: store layout, DDL for chunks_v3 / market_state / opinions, PIT rules and label rules. Its "Manager review" section overrides the rest of it.
- `tasks/QUERY_TEMPLATES_2026-10-27.md`, `tasks/RIPPLE_SCHEMA_REQUIREMENTS_2026-10-28.md`, `tasks/reddit_mining/REPORT.md`.
- The live data: use the `reality-data` MCP `catalog()` for every DB and table with its row counts and date coverage. Use bounded `connect_ro` SQL to check that a column really exists and is filled before you rely on it.
- Raw stores on D: (read-only): `D:\RealityEngine\raw\{index_history,price_bands,concall_pdfs,nse_announcements,...}`.

## Deliverables (write in `tasks/arch_v3/`)
1. **`CASE_MAP.jsonl`.** One row per master-bank case (all 1,030):
   - `mid`;
   - `planner_chain`: the ordered planners, e.g. `["resolve","EVENT","EVIDENCE"]`;
   - for each hop, the exact `table.column`s it reads;
   - `pit_key`: the column that enforces known_at ≤ as_of;
   - `status`: `answerable_now` / `needs_new_table:<name>` / `needs_new_fetch:<source>` / `NOT_IN_DATA:<reason>`.

   This is the core artefact. The reviewer will sample it and check it against the DBs.
2. **`SCHEMA_V3.sql`.** DDL for every new or changed table: chunks_v3, market_state (company_state_daily, membership/sector/theme/mcap intervals, price_band_daily), event_day0, event_leakage_window, xbrl_concept_map, company_metric_series, company_segment_pnl, macro_claim_target / policy_target, plus the partial-gap tables you keep. For each table give:
   - the primary key and **every index**, each with the query it serves;
   - the source of every column (held table/column, or raw store + parser);
   - the build cost estimate (rows, minutes).
3. **`QUERY_LAYER.md`:**
   - the planner contracts (inputs, outputs, SQL shape, PIT clause);
   - the router rules from the master-bank fields to the planner chain;
   - how multi-hop ripple chains are executed;
   - how NOT IN DATA is decided and worded;
   - the hybrid search design for chunks_v3: FTS5 + dense, the filter columns pushed down before ranking, the rerank, and the token budget per answer.
4. **`SPEED_PLAN.md`:**
   - for 20 representative queries spanning the planners, the expected plan (which index) and a **measured** time;
   - measure on today's DBs where the tables exist (`EXPLAIN QUERY PLAN` + timing via connect_ro);
   - where a table doesn't exist yet, build a tiny `.tmp` SQLite prototype with about 10k synthetic rows of the proposed DDL and time it there.
5. **`COVERAGE.md`:**
   - CASE_MAP status counts, overall and per family / entity level / bank;
   - the projected answerable % after the new tables;
   - a list of every NOT_IN_DATA case with its reason;
   - the top gaps still open.

   The target is a design under which at least 95% of cases are answerable (NOT_IN_DATA counts only when the data truly doesn't exist anywhere we can fetch).
6. **`PILOT_SPEC.md`:**
   - the exact pilot universe (ISINs);
   - the doc types and counts;
   - which tables are built for the pilot;
   - the build order with dependencies;
   - the re-run harness design (how all 1,030 cases are executed and graded automatically);
   - the checklist gates: ≥95%, 0 PIT violations, 30/30 regressions, search p95 < 2 s, tag precision ≥ 0.90.

## Rules
- Read-only on every DB (`connect_ro`) and on D:. Write only in this worktree (`tasks/arch_v3/`, `.tmp/`).
- No network, no paid embeddings, no commits.
- **No chunking or loading of real data:** the pilot is built later, from your spec. Synthetic prototypes in `.tmp` only.
- Don't hand-wave. Every table/column you rely on as "held" must be verified with a query. Note the row count and fill rate in CASE_MAP.
- If a master-bank case is ambiguous, map it to the most reasonable reading and flag it. Don't drop it.

## Acceptance checks
1. CASE_MAP.jsonl has 1,030 rows with unique mids, and every row has `planner_chain` and `status`.
2. SCHEMA_V3.sql parses in SQLite (`sqlite3 :memory: < SCHEMA_V3.sql`).
3. SPEED_PLAN.md has 20 timed queries.
4. COVERAGE.md shows projected answerable ≥ 95%, or explains exactly which cases block it and why.

## Test command(s)
```bash
python -c "import json,sqlite3;r=[json.loads(l) for l in open('tasks/arch_v3/CASE_MAP.jsonl',encoding='utf-8')];assert len(r)==1030 and len({x['mid'] for x in r})==1030 and all(x.get('planner_chain') and x.get('status') for x in r);c=sqlite3.connect(':memory:');c.executescript(open('tasks/arch_v3/SCHEMA_V3.sql',encoding='utf-8').read());print('ok')"
```

## Report
Give:
- the coverage numbers (now, and projected after the new tables);
- the 10 biggest design decisions and where you disagree with the reviewer's draft;
- the 20-query timing table;
- the open risks;
- your tool-call count.
