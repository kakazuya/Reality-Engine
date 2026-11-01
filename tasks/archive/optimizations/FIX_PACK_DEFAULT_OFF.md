# Task — make `start_worker(context_pack=...)` opt-in (default false)

## Goal
`start_worker` no longer attaches the context pack unless `context_pack=true` is passed; docs and tests match.

## Why
Three A/B tests on 2026-10-24/25 showed no accuracy or speed gain from the pack and ~30% more output tokens.

## Files to touch
- `plugins/dsh-worker/server/core.py` — `start_worker(..., context_pack: bool = False)` (line ~1005).
- `plugins/dsh-worker/server/plugin_server.py` — same default (line ~157) and the description text "context_pack (default true)" → "(default false; opt-in)".
- `plugins/dsh-worker/README.md` (~line 192) and `plugins/dsh-worker/skills/dsh-worker/SKILL.md` — say it is opt-in and why (one sentence).
- `reality_engine/tests/test_dsh_worker_plugin.py` — update the tests below.
- Do not touch: `supervisor.py`, `gitutil.py`, `context_pack.py`, the builder.

## Steps
1. Flip both defaults.
2. These 6 tests fail after the flip (verified): `test_start_worker_attaches_context_pack_header`,
   `test_start_worker_regenerates_stale_pack`, `test_start_worker_stale_pack_failure_is_warning` → pass
   `context_pack=True` explicitly; `test_start_defaults_argv_and_result`,
   `test_controller_lease_renewal_is_explicit_and_restart_cannot_extend`,
   `test_worktree_start_auto_commit_branch_and_data_env` → update their expected brief/record to the no-pack default.
3. Add one test: a default start records `context_pack.enabled == false` and the delivered brief has no pack header.

## Acceptance checks
1. `python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_dsh_worker_stress reality_engine.tests.test_dsh_worker_sandbox` → all pass.
2. `git diff --stat` touches only the files above.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_dsh_worker_plugin
```

## Budget
≤ 15 tool calls before the first edit; ≤ 60 total; ≤ 30 min; $0 paid.

## Report format
1. What changed  2. Verified (counts)  3. Outside-sandbox steps  4. Open problems  5. Tool calls before first edit / total.
