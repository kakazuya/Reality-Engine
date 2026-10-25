# Task — run the dsh-worker and code-intel test suites in one process

## Goal
`python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_code_intel` passes in a
single process (today it fails at import).

## Why
`plugins/dsh-worker/server/core.py` and `plugins/code-intel/server/core.py` are both imported as the top-level module
`core` (each test module puts its plugin's `server/` dir on `sys.path`). Whichever loads first wins, so the second suite
fails with `AttributeError: module 'core' has no attribute 'langserver_command'`. Any combined test run (merge queue,
full discovery) breaks.

## Files to touch
- `reality_engine/tests/test_code_intel.py` — load the code-intel server modules under a unique name.
- `plugins/code-intel/server/*.py` — only if their own imports must change; the server must still start as
  `python plugins/code-intel/server/server.py` (that is how `.mcp.json` launches it).
- Do not touch: anything under `plugins/dsh-worker/`, `.mcp.json`.

## Inputs/data
None (no databases).

## Steps
1. Reproduce: run the Goal command, see the import failure.
2. Make the code-intel tests import its modules without claiming the global name `core` (e.g. `importlib.util`
   with a unique module name, or package-qualify), keeping the server runnable as a script.
3. Confirm both orders work.

## Acceptance checks
1. `python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_code_intel` → OK.
2. `python -m unittest reality_engine.tests.test_code_intel reality_engine.tests.test_dsh_worker_plugin` → OK.
3. `python plugins/code-intel/tests/acceptance_check.py` → ALL CHECKS PASSED.
4. `git diff --stat` touches only the files listed above.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_code_intel
python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_code_intel
```

## Budget
- ≤ 25 tool calls before the first edit; ≤ 80 total; ≤ 40 min wall; $0 paid.

## Report format
1. What changed (files, one line each).
2. How it was verified (commands + exact pass counts).
3. Anything the controller must install/run outside the worker sandbox.
4. Open problems.
5. Tool calls before first edit / total.

## Out of scope
Renaming the dsh-worker modules; changing how either MCP server is registered or launched.
