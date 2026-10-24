# Toolbelt — ready scripts for dsh workers

One tested CLI per operation the 2026-10-24 workers rebuilt from scratch. Every
tool prints JSON by default (`--format table` for humans), never prints secrets,
and opens live SQLite stores read-only through
`reality_engine.db.readonly.connect_ro` unless the flag says otherwise.

Databases resolve through `REALITY_DATA_ROOT` when set (the main checkout's
`reality_engine/data`), else this worktree's `reality_engine/data`.

| Tool | Purpose | Example |
|---|---|---|
| `sample_rows` | Random row sample via `rowid` ranges (no `ORDER BY RANDOM()` scan) or `--schema` with columns, indexes and `sqlite_stat1` estimate. | `python -m reality_engine.toolbelt.sample_rows --db equity_intelligence --table insider_trades_v2 --n 5` |
| `find_docs` | Resolve a symbol/ISIN/doc-type/date window across `corporate_documents`, `raw_documents`, `ar_docs`, `deck_sources`, `cc_docs`; real filing date, disk presence, chunk count, read status. | `python -m reality_engine.toolbelt.find_docs --symbol DEEDEV --doc-type CONCALL_TRANSCRIPT` |
| `drive_fetch` | Fetch from `gdrive:InfoDiffusion_archive` by archive path, sha256 (cached index) or the DB's stale `local_path`; a drifted crawl-date prefix falls back to the same folder's `_<hash8>_<rest>` suffix (`matched_by`, `alternates`), `--keep-remote-name`, `--dry-run`, `--verify`, per-file ok/missing/blocked. | `python -m reality_engine.toolbelt.drive_fetch --dry-run "C:\\...\\data\\pdfs\\SYM\\ANNUAL_REPORT\\x.pdf"` |
| `render_pages` | PDF → PNG for chosen pages at the deck pipeline's raster density; `--text` dumps the text layer with `text_coverage` and the low-text/deck routing flags. | `python -m reality_engine.toolbelt.render_pages --pdf .tmp/x.pdf --pages 3,5-7` |
| `cost_ledger` | Append-only paid-call ledger (`tasks/ledgers/spend.jsonl`); `--cap` refuses a call that would exceed the budget, `--report` totals by purpose/model/job. | `python -m reality_engine.toolbelt.cost_ledger --report --scope concall_facts` |
| `mod_test` | Claude Code mod checks: `claude plugin validate`, external-tsconfig `tsc`, per-file `claude plugin test`; merges the `claude-plugin-test-report` lines. | `python -m reality_engine.toolbelt.mod_test plugins/dsh-workers-pane` |
| `job_peek` | Compact dsh job view: phase, elapsed, tool calls by tool, last activity, latest progress digest, `result.md` head — tail-read only. | `python -m reality_engine.toolbelt.job_peek <job_dir>` |

Tests: `python -m unittest reality_engine.tests.test_toolbelt`.
