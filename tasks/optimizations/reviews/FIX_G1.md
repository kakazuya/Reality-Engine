# Fix task — G1 data-gather review defects

## Goal
Fix all 7 reviewer defects below in this worktree (`C:\Users\warri\Downloads\IDM-worktrees\20261025T123255Z-3274fb3e`,
branch `dsh/20261025T123255Z-3274fb3e`) with a test for each, and change nothing else.

## Why
The independent review of G1 (data-gather MCP) passed with notes. This server lets cheap models start jobs that
write live DBs, and it edits `plugins/dsh-worker/server/core.py`, which runs unsandboxed for every job. So every gate
must hold on its own.

## Reviewer defects (verbatim)
1. gather.py:309-325 — no cap when the approval omits `max_days`: `_window({}, "2000-01-01", None)` returned a 9791-day window. Fix: `max_days = approval.get("max_days") or DEFAULT_WINDOW_DAYS` before the span check.
2. gather.py:376-378 — `confirm=True` also bypasses the registry's `off_peak_only`/`market_hours` (core.py:3507-3528); a future approved feed with `off_peak_only: true` and no `net:` lock starts in peak. Fix: refuse when `entry["off_peak_only"] and is_peak(now)`.
3. gather.py:299-304 / feeds.py:159-163 — `parse_day` truncates to 10 chars, so `start="2026-01-01 --x"` is accepted instead of refused; strictness only holds because core re-serializes. Fix: strict date check in `_window` (`re.fullmatch` + `date.fromisoformat`).
4. tests/test_data_gather.py:227-229 — compares whole `freshness` dicts incl. volatile `checked_at`; live calls straddled 5s and mismatched. Fix: drop `checked_at` before comparing.
5. core.py:3500-3505 — regex accepts impossible dates ("2026-02-30"); `jobs._coerce_day` then raises `RegistryError` (ValueError, not `PluginError`) → `_safe` returns `internal_error`. Fix: `date.fromisoformat` inside the try, re-raise `PluginError("window_invalid")`.
6. gather.py:87-90 — approval file is resolved inside the running checkout, no env pin; a profile pointed at a worktree reads the worker-writable copy. Fix: `DSH_DATA_GATHER_APPROVED` outside the repo, default `~/.dsh/data-gather/approved.yaml`.
7. gather.py:336-338/379 — `tables_truncated` (writes >12 tables) is captured but never surfaced by `verify_feed`, so verification is silently partial. Fix: include it in the result and fail when true.

## Manager decisions
- Defect 6: approval lives at `~/.dsh/data-gather/approved.yaml` (outside every checkout). If that file is missing,
  `run_feed` refuses everything (`approval_file_missing`); it never falls back to the repo copy. Keep the repo
  `plugins/data-gather/approved.yaml` as the documented template only, and say so in the README. Do not create the
  real file. Claude creates it.
- `DEFAULT_WINDOW_DAYS` = 31.

## Files to touch
- `plugins/data-gather/server/gather.py`, `feeds.py`, `README.md`, `tests/test_data_gather.py`
- `plugins/dsh-worker/server/core.py` (defect 5 only), `reality_engine/tests/test_dsh_worker_plugin.py` (its test)

## Acceptance checks
1. One new or updated test per defect, each failing before the fix and passing after.
2. `python -m unittest discover -s plugins/data-gather/tests -p "test_*.py"` and `python -m unittest reality_engine.tests.test_dsh_worker_plugin` pass.
   If the sandbox blocks temp dirs, say so; Claude reruns them outside the sandbox.
3. `git diff --stat` touches only the files listed.

## Test command(s)
```bash
python -m unittest discover -s plugins/data-gather/tests -p "test_*.py"
```

## Budget
≤ 10 tool calls before the first edit; ≤ 60 total; $0 paid. Do not commit (Claude commits). Do not start any feed.

## Report format
1. Per defect: what changed (file:line) + test name  2. Test results  3. Open problems  4. Tool calls.
