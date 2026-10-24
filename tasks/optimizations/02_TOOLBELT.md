# Task 02 — Shared toolbelt of ready scripts for workers

Read `tasks/optimizations/00_SHARED_CONTEXT.md` first. Worktree task. Independent of Tasks 01/03/04 — touch only
`reality_engine/toolbelt/`, its tests, and one line in `.gitignore` if needed.

## Goal

The operations 2026-10-24 workers rebuilt from scratch, again and again, become one tested CLI each, so a worker
calls `python -m reality_engine.toolbelt.<tool> ...` instead of writing 5–30 tool calls of ad-hoc PowerShell.

## Deliverables — package `reality_engine/toolbelt/` (each module: argparse CLI + importable function + docstring
with 2 examples; JSON output by default with `--format table` option; never prints secrets; read-only on live DBs
unless the flag says otherwise)

1. `sample_rows` — `--db <name|path> --table T [--where SQL] [--cols a,b] [--n 20] [--seed 7] [--stratify col]`
   via `connect_ro` (timeout 60 s); random sample using `rowid` ranges (no `ORDER BY RANDOM()` on big tables).
   Also `--schema` prints columns + indexes + row estimate (sqlite_stat1).
2. `find_docs` — resolve documents by symbol/ISIN/doc_type/date window across `corporate_documents`,
   `raw_documents`, `ar_docs` (ar_facts.db), `deck_sources` (deck_figures.db), `cc_docs` (concall_facts.db):
   returns ids, real filing date (bse_dissem_ts → publication_date → call_date; flags undated), local path + whether
   it exists on disk, chunk count (indexed lookup per doc_id, not a GROUP BY scan), read/extract status per store.
3. `drive_fetch` — fetch files from `gdrive:InfoDiffusion_archive` by (a) relative path, (b) sha256 (build/cache an
   index `./.tmp/drive_index.json` from `rclone lsjson -R --hash` of the needed folder, refresh with `--reindex`), or
   (c) the DB's stale `local_path` (maps `...\reality_engine\data\pdfs\X` → `pdfs/X`, `D:\RealityEngine\pdfs\X` →
   `D_pdfs/X`, decks → `decks/...`; discover the deck mapping by reading `deck_sources.local_path` samples). Options:
   `--dest DIR` (default: the original local path; `--dest` required inside a sandbox), `--transfers 8`, `--dry-run`,
   `--verify` (md5 vs Drive). Prints per-file ok/missing/blocked (Drive 403 "abusive" → `blocked`, suggest BSE).
4. `render_pages` — PDF → PNG for given pages (`--pdf P --pages 3,5-7 --dpi <default = the deck pipeline's DPI;
   find it in the deck reader code>`), PyMuPDF; also `--text` to dump the text layer with char counts and a
   `text_coverage` score per page (the same "low-text page" rule the deck/AR pipelines use — find and reuse it).
5. `cost_ledger` — append-only paid-call ledger `tasks/ledgers/spend.jsonl` (`--add provider model in_tok out_tok usd
   purpose job_id`, `--cap USD --scope purpose` → exits non-zero when the cap would be exceeded, `--report`).
   Importable `charge(...)` that raises `BudgetExceeded`. Reads provider-reported cost when given, else tokens×price.
6. `mod_test` — run a Claude Code mod's checks the way that works in the sandbox: validate + `tsc` (with the
   tsconfig outside the mod, `npm_config_cache=./.tmp/npm-cache`) + each `hooks/*.test.ts*` via
   `claude plugin test --file <abs> <abs mod>`; aggregates the `claude-plugin-test-report` JSON lines into one
   summary (files, tests, failures).
7. `job_peek` — compact view of a dsh job dir (phase, elapsed, tool calls by tool, last 10 activity lines, latest
   progress digest, result.md head) without loading whole event files (tail-read).
8. `README.md` in the package: one table (tool → purpose → example) — Task 01's context pack will include it.

## Acceptance checks

1. `python -m reality_engine.toolbelt.<tool> --help` works for all 7.
2. Unit tests `reality_engine/tests/test_toolbelt.py`: in-memory SQLite fixtures for sample_rows/find_docs; a tiny
   generated PDF (PyMuPDF) for render_pages; a fake `rclone` (subprocess stub) for drive_fetch mapping/hash index;
   ledger cap behaviour; mod_test report aggregation from canned JSON lines; job_peek on a fixture job dir. All pass.
3. Live smoke (read-only, allowed): `sample_rows --db equity_intelligence --table insider_trades_v2 --n 5` and
   `find_docs --symbol DEEDEV --doc-type CONCALL_TRANSCRIPT` return within 10 s each; `drive_fetch --dry-run` on
   one known FY26 AR path reports it present on Drive (e.g. any `pdfs/<SYM>/ANNUAL_REPORT/...` from `ar_docs`).
   `render_pages` on a PDF you fetch into `./.tmp/` works.
4. No secrets printed; no writes to live DBs or data folders.

## Out of scope

Context pack (01), sandbox/permissions (03), LSP (04). Do not change existing scripts' behaviour; you may import
helpers from them.

## Budget

≤ 25 tool calls before first edit; target ≤ 140 total; wall ≤ 60 min. No paid calls.
