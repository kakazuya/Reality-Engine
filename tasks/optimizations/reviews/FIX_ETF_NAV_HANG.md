# Fix task — `fetch_etf_nav.py` hangs with no output

## Problem
Job `etf_nav` (jobs.yaml) ran twice on 2026-10-25. The first run went 45 min, the second 16 min, and both were
cancelled. Neither printed anything to stdout/stderr or wrote a raw file under `D:\RealityEngine\raw`.
- `reality_engine/scripts/fetch_etf_nav.py:99-100` calls `requests.get(AMFI..., timeout=300)`. That timeout applies
  per socket read, so a server that trickles bytes never trips it.
- The hang may also be somewhere else: `load_px`, the NSE part, or a `sqlite3.connect(DB, timeout=600)` waiting on a
  lock (line 228). Find out which with a bounded probe before changing anything.

## Do
1. **Diagnose.** Run the script on a temp copy of the DB, or add `--dry-run`/`--check` logging, with
   `python -u` and `faulthandler.dump_traceback_later(120, repeat=True)`, so you can see where it blocks.
   - Do not write the live `equity_intelligence.db`.
   - Keep network probes small: one month window.
2. **Fix.**
   - Every network call gets a total wall-clock cap: stream with `iter_content` and abort past N seconds
     (default 120, configurable) and past a max size.
   - Each call gets 3 retries with backoff, then a clear error line.
   - Print one progress line per month file (`flush=True`).
   - If the DB connect waits on a lock, fail fast with a message that names the lock holder.
   - Raw files go under `config.raw_dir(...)` on D, as now.
3. Add `reality_engine/tests/test_fetch_etf_nav_timeout.py`. It mocks a slow trickling response and asserts that
   the cap fires. Use `.tmp/` for temp dirs.

## Acceptance
- The test passes: `python -m unittest reality_engine.tests.test_fetch_etf_nav_timeout`.
- A one-month real probe (Oct 2026), run outside the live DB, finishes in under 5 min or fails with a clear message.
  Report which it was, with the time taken.
- `git diff --stat` touches only `fetch_etf_nav.py` and the new test.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_fetch_etf_nav_timeout
```

## Budget
≤ 10 tool calls before the first edit; ≤ 60 total; $0 paid. No live DB writes.

## Report
1. Where it hung (evidence)  2. Change (file:line)  3. Probe result  4. Tool calls.
