# Shared context for every optimisation worker — READ THIS FIRST, then your own brief

Written by Claude on 2026-10-25 from what the 2026-10-24 workers already discovered, so you do not rediscover it.
**Budget rule: ≤ 25 tool calls before your first file edit.** Everything you need to start is below or in your brief.
If something here is wrong, fix it in your report — do not silently work around it.

## Why this exists

On 2026-10-24, DeepSeek workers took 90–270 tool calls and 30–50 min per task; most of it was orientation (finding
code/schemas/test commands) and sandbox workarounds (temp dirs, installs, blocked commits). These four tasks remove
that cost for every future worker.

## Machine

- Windows 11 laptop "Sumit", 8 logical cores, 17 GB RAM, GTX 1050 Ti 4 GB (Pascal sm_61; ~1.1 GB used at idle).
  C: 460 GB SSD (~150 GB free). D: is Shivam's personal 931 GB disk — only `D:\RealityEngine\` is ours.
- Python: `C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe` (3.14.7). Not installed for 3.14:
  `onnxruntime` (no 3.14 wheel), so local ONNX embedders are unavailable. `xlrd` installed today. Node/npm present;
  `npx -p typescript@5.9.3 tsc` works. `claude` CLI at `~/.local/bin/claude`. `rclone` on PATH (remote `gdrive:`).
- pip from this network: add `--timeout 120 --retries 5` (default 15 s read timeouts failed on 2026-10-24).
- Shell: your `pwsh` runs in ConstrainedLanguage mode; every call prints two `InvalidOperation: Cannot create
  type...` lines — harmless noise, ignore it. Prefer `python -c` / small `.py` scripts for anything non-trivial.

## Repo (root `C:\Users\warri\Downloads\Info_Diffusion_Model`, git main, remote github kakazuya/Reality-Engine)

- `AGENTS.md` (rules; §3.2 storage + querying rule), `tasks/FRAMEWORK.md` (authority), `tasks/STATE.md` (live state;
  read the last two sections only).
- `reality_engine/` — `db/` (`readonly.py` = `connect_ro`, `repository.py`, `schema.sql`), `ingestion/`
  (`pdf_ingestor.py`, `nse_client.py`…), `processing/`, `scripts/` (~all jobs; `resource_watchdog.py` has
  `user_env()` for API keys), `tests/` (unittest).
- `plugins/dsh-worker/` — the MCP server that runs you: `server/core.py` (tools: start_worker, worker_status,
  worker_progress, message_worker, merge_worker, push, start_job…), `server/supervisor.py`, `server/progress.py`
  (20-min digests, merged 2026-10-24), `server/jobs.py` + `jobs.yaml` (57 data jobs, all disabled), `README.md`,
  `skills/dsh-worker/SKILL.md`. Runtime: `plugins/dsh-worker/runtime/jobs/<job_id>/` (status.json, heartbeat.json,
  result.md, result.md.events.jsonl, progress.jsonl/progress.md, brief.md, steering.jsonl).
- `plugins/reality-data/server/` — the read-only data MCP (`core.py`, `catalog.py`, `search_docs.py`,
  `catalog_descriptions.yaml`, `catalog_cache.json`). Tools: catalog, resolve, price, facts, search_docs, sql.
- `plugins/dsh-workers-pane/` — Claude Code mod (pane) installed as user plugin `dsh-workers@reality-engine` via
  `.claude-plugin/marketplace.json` at repo root.
- `tasks/dsh_tasks/` — every 2026-10-24 brief; `tasks/handoff/` — paused work; `tasks/research/` — reports.

## Data (`reality_engine/data/`, SQLite WAL; never write without being told; one writer per DB)

| DB | Size / rows | Use |
|---|---|---|
| `equity_intelligence.db` | ~50 GB | main: `master_companies`, `security_master`, `symbol_isin_history`, `corporate_documents` (doc_type, local_file_path, is_processed 0/1/2, source_url, bse_dissem_ts/publication_date/call_date — **doc_date is crawl date, never use it as a filing date**), `raw_documents` (now has symbol/isin/symbol_source), `document_chunks` (2.94M rows — **never correlated subqueries / unindexed GROUP BY on it**), `intelligence_fts`, `mkt_*` market tables, `daily_price_delivery` (to 2026-10-23), `insider_trades_v2` (333,712; `known_at` = PIT key) |
| `ar_facts.db` | ~20 GB | `ar_docs` (33,705; fiscal_year, path, status), `ar_facts` (~33M) |
| `deck_figures.db` | | `pages` (815,837), `facts` (12M), `outputs`, `chart_trends`, `deck_sources`, `spend` |
| `concall_facts.db` | | `cc_docs` (status ok/skip_*/queued_429/error, model, filed_at), `cc_items`, `cc_item_checks` |
| `results_xbrl.db` | | quarterly XBRL filings/facts |
| `bse_announcements.db` | ~1.95M | announcement metadata |
| `snapshots/truth_2026-10-19.duckdb` | | read-only PIT research snapshot |
| `vector_index_*` folders | | NumPy indexes (`nemotron8b` 4096-d, `qwen8b_ar` partial, old bge) |

Read with `from reality_engine.db.readonly import connect_ro; con = connect_ro(path, timeout_s=60)` (mode=ro,
query_only, temp_store=MEMORY, per-statement timeout raising `QueryTimeout`). Or call the reality-data MCP tools.

## Tests (exact commands)

- Whole repo: `python -m unittest discover -s reality_engine/tests -p "test_*.py"` (slow; run your module first).
- dsh-worker: `python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_dsh_worker_stress` (~210 s, 73 tests).
- A Claude Code mod: `claude plugin validate <abs mod dir>`; tests one file at a time:
  `claude plugin test --file <abs test file> <abs mod dir>` (the multi-file runner fails in the sandbox: EPERM spawn).
- Data-touching tests must use in-memory/temp fixtures, never the live DBs.

## Known sandbox limits (until task 03 fixes them) and the working workaround

| Problem seen 2026-10-24 | Workaround that worked |
|---|---|
| `tempfile.mkdtemp()` dirs unwritable (Windows DACL of the sandbox token) | create `./.tmp/` inside your workspace and pass it explicitly (`dir=`); set `TMP`/`TEMP` to it for subprocesses |
| Worktree cannot write `reality_engine/data`, `D:\RealityEngine`, `~/.dsh`, `~/.claude`, the Startup folder | stage outputs in the worktree; Claude installs/copies after review |
| `git commit` from a worktree blocked when its index lives in the main `.git` | leave changes uncommitted; the supervisor auto-commits a non-empty diff when you finish successfully |
| npm/npx write a cache into the repo (`.cache/npm`) | set `npm_config_cache` to `./.tmp/npm-cache`; it is gitignored there |
| Long processes started from a shell die with the parent | for anything that must outlive you, write the command for Claude (who launches via WMI) |
| `message_worker` status pings could end your run | you will not be pinged for status any more; a follow-up is a real instruction — handle it and continue |

## Conventions (non-negotiable)

- Point-in-time: anything used for research carries `known_at`; never use data unknown at decision time.
- Free models only on subscriptions; any paid API call needs an explicit budget in your brief.
  Keys: `reality_engine.scripts.resource_watchdog.user_env()[NAME]`; never print key values.
  Go: key 1 (`OPENCODE_GO_API_KEY`) is dead; key 2 + Kilo keys 1/2 work; every Go call sends a stable
  `x-opencode-session` via `go_session.session_id` (never uuid4 per call).
- Newest → oldest for any backfill. One writer per SQLite DB. No `git stash`. No pushing (Claude pushes).
- Match the surrounding code style (comment density, naming). Additive schema changes only.

## Report format (final answer, every task)

1. What changed (files, one line each). 2. How it was verified (commands + exact pass counts). 3. Anything Claude
must install/run outside your sandbox (exact commands). 4. Open problems. 5. Tool calls before first edit / total.
