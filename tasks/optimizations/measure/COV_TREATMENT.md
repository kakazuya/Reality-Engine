## Worker context pack (auto-attached)
Read the context pack FIRST, before any other orientation: C:\Users\warri\Downloads\Info_Diffusion_Model\tasks\worker_context\CONTEXT.md
It is the generated repo/data/test/sandbox map for this checkout; do not rediscover it file by file.
Budget: reach your first useful edit within <= 25 tool calls. Read the pack once, then only the files the task names.
The pack is generated, so the repo wins if they disagree; note the drift in your report.
Brief contract (when you write briefs): C:\Users\warri\Downloads\Info_Diffusion_Model\tasks\worker_context\BRIEF_TEMPLATE.md
Final report format: 1) what changed (files, one line each) 2) how verified (commands + exact pass counts)
3) anything the controller must install/run outside the sandbox 4) open problems 5) tool calls before first edit / total.

# Task — `coverage_peek`: one command that shows what data we hold for a symbol

## Goal
`python -m reality_engine.toolbelt.coverage_peek --symbol DEEDEV` prints, per data store that holds company-level
data (filings/announcements, concall transcripts and extracted concall facts, annual reports and AR facts, investor
decks and deck figures, quarterly XBRL results, prices), the row count and the earliest/latest date for that symbol.

## Why
Before any backtest we must know, per stock, which datasets exist and how fresh they are. Today that takes a dozen
ad-hoc queries across several SQLite databases and a DuckDB snapshot.

## Files to touch
- `reality_engine/toolbelt/coverage_peek.py` — new (follow the style of the other toolbelt tools).
- `reality_engine/tests/test_coverage_peek.py` — new, in-memory fixtures only.
- `reality_engine/toolbelt/README.md` — one row.
- Do not touch anything else.

## Inputs/data
The live databases (read-only). You must find which tables hold each kind of data and how they key the symbol
(symbol vs ISIN vs internal id) yourself. Never write to any database. Keep every query bounded and indexed.

## Acceptance checks
1. `python -m reality_engine.toolbelt.coverage_peek --symbol DEEDEV` returns within 20 s and lists at least 5 stores
   with counts and date ranges; `--json` gives the same as JSON.
2. An unknown symbol prints a clear "not found" and exits 2.
3. `python -m unittest reality_engine.tests.test_coverage_peek` passes.
4. No writes to any database; `git diff --stat` touches only the files above.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_coverage_peek
```

## Budget
- ≤ 25 tool calls before the first edit; ≤ 120 total; ≤ 60 min wall; $0 paid.

## Report format
1. What changed (files, one line each).
2. How it was verified (commands + exact pass counts).
3. Anything the controller must install/run outside the worker sandbox.
4. Open problems.
5. Tool calls before first edit / total.

## Out of scope
Fetching missing data; changing any schema; a UI.

## Tools available to you (use before grep/rediscovery)
- `mcp__code-intel__definition|references|callers|symbols|hover|diagnostics|module_map` — LSP answers over this repo.
- `python -m reality_engine.toolbelt.<tool> --help` — sample_rows, find_docs, drive_fetch, render_pages, cost_ledger, mod_test, job_peek (`reality_engine/toolbelt/README.md`).
