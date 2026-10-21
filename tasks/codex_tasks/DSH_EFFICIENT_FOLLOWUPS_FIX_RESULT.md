# Efficient same-conversation follow-ups + controller lease — result

DeepSeek/dsh implementation worker, 21-Oct-2026. Scope was limited to
`plugins/dsh-worker/`, `reality_engine/scripts/{run_deepseek_harness.py,
dsh_heartbeat.py,dsh_heartbeat_control.mjs}`, directly relevant tests/fixtures,
and this note. No FRAMEWORK, secret, database, security-setting, push/upload,
install/cache, or additional model-worker changes were made. H01 untouched.

## What changed

### 1. Same-conversation waiting without shell sleeps or polling

Inspected the installed dsh `0.2.1-rc.2` APIs (`@deepseek-ai/dsh-agent`,
`dsh-agent-loop`). The supported hook is the awaited serial
`agent/turn-stopping` event: the agent loop awaits it before committing turn
closure, and `agent.steer()` from it makes the loop re-read its inbox and run one
more step in the same turn/conversation.

- `dsh_heartbeat_control.mjs` now optionally waits at `agent/turn-stopping`
  (`followupWaitSeconds`, default 0) and calls `agent.steer()` exactly once when
  `/followup` delivers a genuine question. It publishes `awaiting-input` with an
  absolute `followup_deadline`.
- `message_worker(kind="followup")` posts to `/followup`; `kind="status"`
  (default) keeps the existing `/ping` status-wrapper behavior. This avoids
  wrapping normal questions as heartbeat checks.
- A follow-up is delivered through exactly one path: the waiter steers it, or,
  if no wait is active, a running turn is steered directly. `/followup` rejects
  wrong run/session/token, duplicate `ping_id`, oversize text, closing turns,
  and non-running agents. Waiting has one bounded timer; timeout, abort, agent
  disposal, and plugin teardown settle it once and leave no listener/timer.
- `run_deepseek_harness.py --followup-wait N` (0..3600, default 0) opts in.
  `start_worker(followup_wait_seconds=...)` exposes it. Default one-shot jobs
  still exit naturally; there is no implicit idle listener.
- While waiting, the Python supervisor reads the descriptor and suppresses
  heartbeat pings. It trusts the wait only while an absolute deadline is
  present and unexpired (plus a small grace), so a stale/wedged descriptor
  cannot silence supervision. On exit it restarts the idle anchor; overdue
  leases make the next idle check due immediately. Normal 900 s/two-miss
  supervision for productive jobs is unchanged.
- Committed assistant `text` events are persisted progressively to the bounded
  result file (atomic replace). Thinking/reasoning and event logs are excluded.
  Lease expiry/cancel during productive work therefore preserves the latest
  committed answer even though the launcher may be killed before its `finally`.
- During `awaiting_input`, `worker_status` shows `awaiting_input` plus deadline
  and does not mark the deliberate wait stale on an unvalidated flag.
  `worker_result` returns `interim=true`, `final=false`, `result_kind=
  awaiting_input` when applicable.

### 2. Independent controller/orchestrator lease

Added explicitly because Codex can disappear while a responsive model keeps
calling APIs. This is not a fixed task-duration cap.

- Default `controller_lease_seconds=1800`. The MCP server writes
  `controller_lease.json` with an absolute real-wall-clock deadline (not the
  test fake-now used for off-peak gating), job/owner binding, and renewal count.
- New MCP tool `renew_worker_lease(job_id, extend_seconds=1800)` is the only
  renewal path. It may extend at most 30 minutes per explicit call. Status,
  result, list, messaging, worker/model/tool activity, and background timers do
  not renew it. Renewal authority is memory-only, so a restarted MCP server
  cannot extend an existing deadline.
- The supervisor reads the lease independently of model activity and validates
  schema, expected job id, expected owner id, parseable deadline, and a bounded
  future interval. Missing, malformed, copied/wrong-owner, arbitrarily future,
  or expired leases fail closed.
- On expiry/missing/invalid lease the supervisor kills the verified owned
  worker tree, preserves existing result/artifacts, and reports
  `outcome=controller_lease_expired` (startup-invalid lease reports
  `controller_lease_invalid`). Cancellation and normal finalization remove the
  lease. `worker_status` exposes deadline/remaining/expired/error.

## Files changed

- `reality_engine/scripts/dsh_heartbeat_control.mjs`
- `reality_engine/scripts/dsh_heartbeat.py`
- `reality_engine/scripts/run_deepseek_harness.py`
- `plugins/dsh-worker/server/{core.py,heartbeat.py,plugin_server.py,supervisor.py,store.py}`
- `plugins/dsh-worker/skills/dsh-worker/SKILL.md`
- `plugins/dsh-worker/README.md`
- `reality_engine/tests/test_dsh_heartbeat.py`
- `reality_engine/tests/test_dsh_worker_plugin.py`
- `reality_engine/tests/fixtures/dsh_worker_fake_launcher.py`
- this report

## Focused checks actually run

All commands are offline; no paid/live model call was made by this worker.

```powershell
python -m unittest reality_engine.tests.test_dsh_heartbeat.HeartbeatStateTests.test_deliberate_followup_wait_suppresses_idle_ping reality_engine.tests.test_dsh_heartbeat.HeartbeatStateTests.test_expired_followup_lease_makes_ping_due_immediately reality_engine.tests.test_dsh_heartbeat.ControlTransportTests.test_awaiting_descriptor_requires_a_live_absolute_deadline reality_engine.tests.test_dsh_heartbeat.ProcessHeartbeatTests.test_committed_text_is_persisted_before_termination reality_engine.tests.test_dsh_heartbeat.RealDshControlIntegrationTests.test_ten_followups_use_ten_requests_and_one_conversation -v
# Ran 5 tests ... OK (20.6 s)
```

This includes the actual installed dsh, actual shipped control adapter, and a
deterministic local fake OpenAI endpoint: ten sequential questions produced
exactly ten intended answer requests, one dsh conversation/session, no status
prefix, no duplicate delivery, no request during the deliberate idle wait, and
the first answer was readable through the persisted interim result before
Question 2. It also checks natural bounded-wait exit, listener cleanup, and
progressive committed-text persistence before termination.

```powershell
python -m unittest reality_engine.tests.test_dsh_worker_plugin.PluginTests.test_manifest_and_layout reality_engine.tests.test_dsh_worker_plugin.PluginTests.test_message_route_selection_distinguishes_followup_from_status reality_engine.tests.test_dsh_worker_plugin.PluginTests.test_message_transport_unavailable_and_control_seam reality_engine.tests.test_dsh_worker_plugin.PluginTests.test_controller_lease_expiry_stops_endless_worker_and_preserves_partial reality_engine.tests.test_dsh_worker_plugin.PluginTests.test_controller_lease_renewal_is_explicit_and_restart_cannot_extend reality_engine.tests.test_dsh_worker_plugin.PluginTests.test_missing_lease_stops_responsive_worker -v
# Ran 6 tests ... OK (14.3 s)

python -m unittest reality_engine.tests.test_dsh_worker_plugin.PluginTests.test_mcp_initialize_tools_prompt_start_partial_and_cancel reality_engine.tests.test_dsh_worker_plugin.PluginTests.test_start_defaults_argv_and_result -v
# Ran 2 tests ... OK (5.2 s)
```

Lease tests cover: responsive fake worker killed on expiry; missing lease file
kills responsive worker; explicit renewal extends; status/result/list calls and
fake worker activity do not renew; restarted MCP server cannot renew; a
copied/wrong-owner lease is refused without extending; cancellation removes the
lease; partial output is preserved and reported.

```powershell
python -m py_compile <changed Python files>
node --check reality_engine/scripts/dsh_heartbeat_control.mjs
# both passed
```

## Limits and reload

- No live paid/native MCP smoke was performed by this worker (per brief). Codex
  should do at most one bounded native smoke after review/install.
- The source plugin in `plugins/dsh-worker/` is changed, but the installed Codex
  cache still contains the previous build. Codex must reinstall the plugin into
  its cache and restart the Codex host/MCP session before the new tools/options
  (`renew_worker_lease`, `followup_wait_seconds`) are visible. No cache edit was
  made here.
- The currently running job launched on the old plugin is not retroactively
  protected by the lease or the new wait; Codex must cancel it explicitly if
  desired.
- The `/followup` route's MCP plumbing is covered by focused route/validation
  tests; the real dsh ten-question proof calls the shipped control endpoint via
  the Python `ControlTransport` (`followup`) because that is the actual wire
  contract. A full MCP-client-to-real-dsh smoke remains the reviewer step.
- `followup_wait_seconds=0` is the default; any caller wanting sequential
  same-conversation follow-ups must opt in and send `kind="followup"`.
- Lease renewal after MCP restart is deliberately refused. A productive job can
  continue indefinitely only while its controller explicitly renews before the
  current deadline; this is the intended Codex-disappearance guard.

## Follow-up: deterministic lease-renewal fixture (Codex 41-test run)

Codex's independent 41-test run passed 40 and failed only
`test_controller_lease_renewal_is_explicit_and_restart_cannot_extend`. The
fixture's initial lease is 4 seconds, and it renewed for the same 4 seconds; the
store's `iso()` records whole seconds, so after `time.sleep(0.3)` the
reset-from-now deadline could land in the same second as the prior deadline and
the strict `assertGreater` failed nondeterministically (both
`2026-10-21T00:47:43Z`). Production renewal semantics are unchanged
(reset-from-now, not add-to-current-deadline). The test now requests
`extend_seconds=10` and asserts both the extension and `lease_seconds == 10`;
the no-renewal, restarted-manager, wrong-owner, and cancel-removes-lease checks
are retained. Test-only change in
`reality_engine/tests/test_dsh_worker_plugin.py`; no production or other source
changes.

Actual commands and results:

```powershell
python -m unittest reality_engine.tests.test_dsh_worker_plugin.PluginTests.test_controller_lease_renewal_is_explicit_and_restart_cannot_extend -v
# Ran 1 test in 1.856s
# OK

python -m unittest reality_engine.tests.test_dsh_heartbeat.HeartbeatStateTests reality_engine.tests.test_dsh_heartbeat.ControlTransportTests reality_engine.tests.test_dsh_heartbeat.RealDshControlIntegrationTests.test_ten_followups_use_ten_requests_and_one_conversation reality_engine.tests.test_dsh_worker_plugin -q
# Ran 41 tests in 61.157s
# OK
```
