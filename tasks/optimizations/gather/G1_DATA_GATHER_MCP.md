# Task G1 — `data-gather` MCP server so DeepSeek workers run and verify data feeds

## Goal
A stdio MCP server in `plugins/data-gather/` gives dsh workers typed tools to:
- see feed freshness;
- run approved feeds through the existing supervisor, under the same locks;
- verify what each run wrote.

Claude only reviews the reports.

## Why
Data gathering moves to the workers (Shivam, 2026-10-25). Today only Claude can start jobs, through the dsh-worker
MCP `start_job`. The 60 jobs in `plugins/dsh-worker/jobs.yaml` are already fixed scripts that carry `writes` and lock
metadata.

## Files to touch
- New: `plugins/data-gather/server/server.py` (+ modules), `plugins/data-gather/approved.yaml`,
  `plugins/data-gather/tests/`, `plugins/data-gather/README.md`.
- Reuse the job registry, runner and lock code rather than copying it:
  - `plugins/dsh-worker/server/jobs.py`;
  - `core.py` (`start_job`, ~line 3475);
  - `store.py`, `supervisor.py`.

  If importing it needs a small refactor, keep it backwards compatible and covered by the dsh-worker tests.
- Do not edit `~/.dsh/profiles/*`. Put the profile snippet that registers the server in the README; Claude applies it.

## Tool contracts
1. `list_feeds()` returns a compact table, one row per feed:
   - name, description, cadence;
   - freshness, using the existing max-date or count rule;
   - age versus cadence;
   - last run and its outcome;
   - approved yes/no.
2. `gap_report(names=None)`, per feed: expected dates versus dates present (trading days for market feeds), and the
   missing ranges.
3. `run_feed(name, start=None, end=None)`:
   - Refuses unless `name` is in `approved.yaml`, which may also set a maximum date range per feed.
   - Refuses during peak hours (Mon–Fri 06:30–09:30 and 11:30–15:30 IST) for feeds marked net-heavy.
   - Starts the job through the same supervisor with the same `db:`/`net:` locks.
   - Returns a `run_id`, or `resource_busy`.
4. `feed_status(run_id)` returns the phase, the outcome, and the tail of stdout/stderr (≤ 40 lines).
5. `verify_feed(name, run_id)` returns pass/fail per check:
   - row counts before and after for each `writes` table;
   - the new max date;
   - the first 5 new rows: the stored date versus the source's filing/known_at date. `doc_date` is often the crawl
     date, so do not trust it;
   - raw files landed under `REALITY_RAW_ROOT` (default `D:\RealityEngine\raw`), not under `reality_engine/data/`.
- Every read goes through `reality_engine.db.readonly.connect_ro`. The server itself never writes DB rows.

## Steps
1. Read jobs.yaml and the runner code, and design the import boundary.
2. Implement it, with tests that use a fake registry and a fake job (no network).
3. Live read-only check: print `list_feeds()` and `gap_report(["commodity_series","etf_nav"])` in the report.

## Acceptance checks
1. `python -m unittest discover -s plugins/data-gather/tests -p "test_*.py"` passes, and the dsh-worker tests still pass.
2. `run_feed` on an unapproved feed refuses. A peak-hour start of a net-heavy feed refuses (clock injected in tests).
3. The live `list_feeds` freshness matches dsh-worker `list_jobs` for 3 feeds.

## Test command(s)
```bash
python -m unittest discover -s plugins/data-gather/tests -p "test_*.py"
```

## Budget
≤ 20 tool calls before the first edit; ≤ 100 total; $0 paid. Do not start any real feed.

## Report format
1. What changed  2. Live outputs (trimmed)  3. Profile snippet for Claude  4. Open problems  5. Tool calls before first edit / total.
