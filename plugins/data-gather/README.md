# data-gather MCP server

Typed tools for DeepSeek/dsh workers to **see feed freshness, run one approved
feed, and verify what the run actually wrote**. Claude reviews the reports; the
workers do the gathering.

The server is a thin composition layer over the existing dsh-worker plugin. It
does not copy the job registry, the supervisor, the controller lease or the
`db:`/`net:` resource locks:

| concern | reused from |
| --- | --- |
| feed registry, `writes`, cadence, `success_check`, `{start}`/`{date}` expansion | `plugins/dsh-worker/server/jobs.py` |
| starting a job (supervisor, lease, steering, resource locks, status records) | `core.Manager.start_job` |
| freshness (max-date / min-count rule) | `core.Manager.list_jobs` |
| status/tail reads | `core.Manager.job_log` |
| every database read | `reality_engine.db.readonly.connect_ro` (bounded, `query_only`) |

`run_feed` passes `window_start`/`window_end` to `Manager.start_job`, which
threads them to `jobs.expand_argv`; the two new keyword arguments default to
`None`, so existing callers keep the old behaviour (covered by
`test_expand_argv_window_override` in the dsh-worker suite).

## Tools

| tool | returns |
| --- | --- |
| `list_feeds()` | one row per `jobs.yaml` feed: name, description, cadence, live freshness (the dsh-worker rule), age vs cadence, last run + outcome, `net_heavy`, `approved`, `max_days` |
| `gap_report(names=None)` | per market feed: expected NSE trading days vs stored dates in the cadence lookback window, and the missing ranges |
| `run_feed(name, start=None, end=None)` | `run_id` (the job id), or an error such as `approval_file_missing`, `feed_not_approved`, `off_peak_hours`, `market_hours`, `peak_hours`, `window_invalid`, `window_too_large`, `resource_busy` |
| `feed_status(run_id)` | phase, outcome, exit code, ≤ 40 lines each of stdout/stderr |
| `verify_feed(name, run_id)` | pass/fail per check: row count before/after, new max date, first 5 new rows (stored date vs source date), raw files under `REALITY_RAW_ROOT`, raw files under the data root |

### run_feed gates (in order)

1. the feed must exist in `jobs.yaml`;
2. the approval file `~/.dsh/data-gather/approved.yaml` (or
   `$DSH_DATA_GATHER_APPROVED`) must exist — if it does not, every `run_feed`
   is refused with `approval_file_missing`; the server never falls back to the
   repo copy, which is a template only;
3. the feed must be listed in that file — the approval *is* the grant, which is
   why an approved feed runs even though every job ships `enabled: false`;
4. `start`/`end` must be exactly `YYYY-MM-DD` and real calendar dates; a window
   longer than the feed's `max_days` is refused, and an approval without
   `max_days` is capped at `DEFAULT_WINDOW_DAYS` = 31;
5. a feed marked `off_peak_only` is refused in peak hours, and one with
   `market_hours: avoid_market` is refused Mon–Fri 09:15–15:30 IST;
6. a **net-heavy** feed (any `net:` resource lock) is refused during peak hours,
   Mon–Fri 06:30–09:30 and 11:30–15:30 IST;
7. the before-run snapshot is captured, then `Manager.start_job(..., confirm=True)`
   takes the job's own `db:`/`net:` locks and refuses with `resource_busy`.

`confirm=True` exists only to start feeds that ship `enabled: false`; gates 1–6
run before it, so it is not a bypass. Peak/weekday logic is `core.is_peak`; the
market-session gate is `core._market_session`; tests inject the clock, so no
test depends on when the suite runs.

### verify_feed

`run_feed` stores `data-gather/runtime/verify/<run_id>.json` before the
supervisor starts: per `writes` table the row count and max date, plus the
window and the raw-scan timestamp. `verify_feed` compares against that baseline:

* `row_count` — fails only if rows disappeared (`after < before`);
* `max_date` — the new max date, fails if it went backwards;
* `new_rows_source_date` — the first 5 rows after the previous max, stored date
  vs the table's own `known_at`/`filing_date`/`published_date`/… column;
  `doc_date` is the crawl date and is never used as evidence. Tables without a
  second date column report `ok: null` (not applicable) instead of guessing;
* `raw_files` — files under `REALITY_RAW_ROOT` (default `D:\RealityEngine\raw`)
  whose mtime is at or after the run started; `ok: null` when the root is absent;
* `raw_not_in_data_root` — no raw-typed files appeared under `REALITY_DATA_ROOT`
  in the same window;
* `table_snapshot_complete` — fails when the feed writes more than `MAX_TABLES`
  (12) tables: the snapshot then covers only the first 12, so verification
  would be silently partial. The result also carries `tables_checked`,
  `tables_total` and `tables_truncated`.

`ok: false` at the top level means at least one check failed. `ok: null` checks
are counted in `not_applicable`.

## approved.yaml

The live approval file is `~/.dsh/data-gather/approved.yaml`, overridable with
`DSH_DATA_GATHER_APPROVED`. It sits outside every checkout so a worker pointed
at a worktree cannot read (or rewrite) its own approvals. If the file is
missing, `run_feed` refuses everything with `approval_file_missing`.

`plugins/data-gather/approved.yaml` is the **template** only — copy its shape
into the live file. The server never reads the repo copy.

```yaml
schema: data-gather-approved/1
feeds:
  commodity_series:
    max_days: 31        # cap on one run's {start}..{date} window; omitted -> 31
  etf_nav:
    max_days: 7
    # market: false     # skip the trading-day gap report for this feed
```

Only add a feed after its cost, locks and blast radius are reviewed.

## Registering the server (profile snippet — Claude applies this)

Add to the MCP server list of `~/.dsh/profiles/*` (same shape as `.mcp.json`),
pointing at the **main checkout**, not a worktree, so run history and gitignored
data resolve:

```json
{
  "mcpServers": {
    "data-gather": {
      "type": "stdio",
      "command": "C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe",
      "args": [
        "C:/Users/warri/Downloads/Info_Diffusion_Model/plugins/data-gather/server/server.py"
      ],
      "env": {
        "REALITY_DATA_ROOT": "C:/Users/warri/Downloads/Info_Diffusion_Model/reality_engine/data",
        "REALITY_RAW_ROOT": "D:/RealityEngine/raw",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

Optional env: `DSH_DATA_GATHER_RUNTIME` (snapshot dir; defaults to
`<DSH_WORKER_RUNTIME_DIR>/data-gather`, i.e.
`plugins/dsh-worker/runtime/data-gather`) and `DSH_DATA_GATHER_APPROVED`
(approval file; defaults to `~/.dsh/data-gather/approved.yaml`).
`DSH_WORKER_JOBS_FILE`, `DSH_WORKER_REPO_ROOT`, `DSH_WORKER_RUNTIME_DIR` and
`DSH_WORKER_LAUNCHER` are the dsh-worker variables and keep working unchanged.

## Tests

```bash
python -m unittest discover -s plugins/data-gather/tests -p "test_*.py"
```

Offline: a fake registry, a fake feed job that writes a throwaway SQLite
database and a raw file, and the real supervisor. No network, no real feed, no
live database.

## Known limits

* Run history is per `DSH_WORKER_RUNTIME_DIR`; a server started in a worktree
  shows `last_run: null` because the jobs live in the main checkout's runtime.
* The raw-file check uses mtime. A run that copies files with preserved source
  timestamps reads as "no new raw files".
* The trading-day calendar is `equity_intelligence.db:mkt_nse_index_daily`
  (index-keyed on date); a feed whose writes have no `date`/`as_of` column is
  reported `not_a_market_feed` rather than gap-checked.
* `list_feeds` freshness includes a volatile `checked_at`, like `list_jobs`.
