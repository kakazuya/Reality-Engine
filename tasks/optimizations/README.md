# Worker optimisations — launch sheet for the next session (Claude)

Shivam (2026-10-24/25): DeepSeek workers waste most of their time on rediscovery and sandbox workarounds. These four
tasks are the first thing the next session does, after the app restart (which loads dsh-worker progress digests,
merged in `6c0f59e`).

| # | Brief | Worker setup | Depends on | Est. wall |
|---|---|---|---|---|
| 01 | `01_CONTEXT_PACK_AND_BRIEF_TEMPLATE.md` | worktree, workspace-write | — (owns `start_worker` brief assembly) | 60 min |
| 02 | `02_TOOLBELT.md` | worktree, workspace-write | — | 60 min |
| 03 | `03_SANDBOX_AND_FREEDOM.md` | worktree, workspace-write (it designs the freedom modes; it cannot grant them to itself) | — (owns supervisor env/sandbox) | 75 min |
| 04 | `04_LSP_CODE_INTELLIGENCE.md` | worktree, workspace-write | — | 60 min |

All four start **in parallel** (each in its own worktree; 01 and 03 split `plugins/dsh-worker/server/` by ownership
as written in their briefs). Every brief points to `00_SHARED_CONTEXT.md` first.

## Claude's start calls (next session)

For each: `start_worker(task_file="tasks/optimizations/0N_....md", permission="workspace-write",
use_worktree=True, controller_lease_seconds=7200, progress_interval_seconds=1200,
test_cmd=<below>)`; follow progress with `worker_progress()` (no status pings).

- 01 test_cmd: `python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_dsh_worker_stress`
- 02 test_cmd: `python -m unittest reality_engine.tests.test_toolbelt`
- 03 test_cmd: same as 01
- 04 test_cmd: `python -m unittest reality_engine.tests.test_code_intel`

Grant more freedom only after 03 lands (its `write_scope` modes); `"full"` needs Shivam's OK each time.

## Merge order and installs (Claude)

1. Merge 02 and 04 as soon as each passes review (independent).
2. Merge 01, then 03 (both touch `plugins/dsh-worker/server/`; resolve via the merge queue; rerun the dsh suite).
3. Installs outside the sandbox from the reports: basedpyright + code-intel MCP (user scope + dsh profile inserts),
   dsh profile changes from 03 (+ pwsh timeout), `setup_worker_env.py`, generate CONTEXT.md once.
4. Restart the app; then measure: start one small real task with the new setup and compare
   `tool_calls_before_first_edit` against `tasks/worker_context/orientation_baseline.json`. Target: ≥ 50% fewer
   orientation calls.

## After the optimisations (paused work, see `tasks/handoff/`)

Concall runner (`wip/concall-runner-2026-10-24`), chart/image pass (`dsh/20261024T180421Z-eed294f4`), local OCR
pilot (`dsh/20261024T181301Z-e5311613`) — review, then resume with the new worker setup.
