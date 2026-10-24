# Task 01 — Worker context pack + brief template with definition of done

Read `tasks/optimizations/00_SHARED_CONTEXT.md` first. Worktree task. Touches `plugins/dsh-worker/server/` —
coordinate: Task 03 also edits that package; you own **brief assembly in `start_worker`** and the new
`context_pack` module; do not edit `supervisor.py` sandbox/env code (Task 03 owns it).

## Goal

Every new DeepSeek worker starts with an accurate, compact map of the repo, data and rules, so it reaches its first
useful edit in ≤ 25 tool calls instead of 40–100. Briefs follow one template with an explicit definition of done.

## Deliverables

1. `reality_engine/scripts/build_worker_context.py` — generates `tasks/worker_context/CONTEXT.md` (+ optional
   `tasks/worker_context/schemas/<db>.md`). Target ≤ 25k tokens for CONTEXT.md. Content, generated not hand-written
   where possible:
   - **Repo map**: top-level tree to depth 2 with one-line purpose per package/script family (derive from module
     docstrings: first line of each `reality_engine/**/*.py` and `plugins/*/server/*.py`; skip tests/fixtures);
     list the ~40 most-used scripts (count references in `tasks/STATE.md`, `jobs.yaml`, recent `tasks/dsh_tasks/*.md`).
   - **Data map**: for each DB in `reality_engine/data/*.db` + the DuckDB snapshot: tables with row counts (use
     `sqlite_stat1` / `catalog_cache.json` from `plugins/reality-data/server/` — do NOT `COUNT(*)` the 50 GB DB),
     key columns, the curated one-liners from `plugins/reality-data/server/catalog_descriptions.yaml`, date coverage
     where the catalog has it. Put full column lists in `schemas/<db>.md`; CONTEXT.md gets the top 60 tables.
   - **How to query**: `connect_ro` snippet, the reality-data MCP tools and when to prefer each, the document_chunks
     rule, doc_date-is-crawl-date rule, known_at rule.
   - **Tests**: the exact commands from 00_SHARED_CONTEXT; plus a table "module → its test file" built by matching
     `reality_engine/tests/test_*.py` imports.
   - **Sandbox limits + workarounds**: import the table from 00_SHARED_CONTEXT (keep it in one source file:
     `tasks/worker_context/SANDBOX.md`, maintained by Task 03; CONTEXT.md includes it verbatim).
   - **Conventions**: from 00_SHARED_CONTEXT + AGENTS.md §3 rules 2 and 13 (summarised).
   - **Recent decisions**: the last ~30 one-line entries of `reality_engine/data/hotline/decisions.md` if present,
     and the "START HERE"/hand-off sections of `tasks/STATE.md` (last two `## ` sections only).
   - Header with generation time, git HEAD, and a staleness note.
   Deterministic, idempotent, runs in < 60 s, read-only on all DBs.
2. **Nightly refresh**: add job `worker_context` to `plugins/dsh-worker/jobs.yaml` (enabled: false like all others,
   cadence daily, writes only `tasks/worker_context/`, success_check: file mtime < 26 h). Also callable on demand.
3. **Auto-attach in `start_worker`** (`plugins/dsh-worker/server/core.py`; read how `refresh_context` and the brief
   / task_file are assembled today — there is an existing "fresh context file" mechanism per memory note
   *worker full context*; extend it, don't duplicate it): the brief the worker receives = standing header (≤ 15 lines:
   "Read CONTEXT.md first; budget ≤ 25 calls before first edit; report format") + absolute path to CONTEXT.md +
   the task brief. If CONTEXT.md is older than 26 h, regenerate it before launch (bounded 60 s; on failure launch
   anyway with a warning in the job record). New `start_worker` param `context_pack=True` (False skips).
4. `tasks/worker_context/BRIEF_TEMPLATE.md` — sections: **Goal** (1–3 lines) · **Why** · **Files to touch** (exact
   paths; "do not touch" list) · **Inputs/data** (exact tables/files) · **Steps** · **Acceptance checks** (numbered,
   testable) · **Test command(s)** · **Budget** (tool calls, paid $, wall time) · **Report format** · **Out of scope**.
   `start_worker` lints a brief/task_file against it: missing Goal / Acceptance checks / Test command → a `warnings`
   entry in the start response (never a hard failure). Convert one existing brief
   (`tasks/dsh_tasks/WATCHDOG_LAPTOP_2026-10-24.md`) to the template as the worked example
   `tasks/worker_context/EXAMPLE_BRIEF.md`.
5. Update `plugins/dsh-worker/README.md` and `skills/dsh-worker/SKILL.md` (how Claude writes briefs now).

## Acceptance checks

1. `python -m reality_engine.scripts.build_worker_context` writes CONTEXT.md ≤ 25k tokens (count with a simple
   chars/4 estimate; report it) in < 60 s, with all 7 sections, row counts for the 6 DBs, and no secrets
   (grep for `KEY`, `TOKEN`, `sk-`, key values from `user_env()` → none).
2. Running it twice produces identical output except the header timestamp.
3. `start_worker` with a minimal brief → the delivered `brief.md` in the job dir begins with the header + CONTEXT path
   + original brief; `context_pack=False` → original brief only; stale pack triggers a regeneration (test with a fake
   clock / temp file mtime).
4. Brief lint: a brief without "Acceptance checks" → warning returned; template-conformant brief → no warning.
5. Unit tests added to `reality_engine/tests/test_dsh_worker_plugin.py` (or a new `test_worker_context.py`); full
   dsh-worker suite still passes (73 + yours).

## Out of scope

Sandbox/env/permissions (Task 03), toolbelt scripts (Task 02), LSP (Task 04). Do not enable any jobs.yaml job.

## Budget

≤ 25 tool calls before first edit; target ≤ 120 total; wall ≤ 60 min. No paid calls.
