# dsh-worker Codex plugin — implementation handoff

Date: 2026-10-21. Local desktop-only plugin under `plugins/dsh-worker/`. It wraps the existing
`reality_engine/scripts/run_deepseek_harness.py`; it does not change the provider route, model, account,
credentials, or Codex's main model. No plugin was registered globally and no paid model call was made.

## Files

New:

- `plugins/dsh-worker/.codex-plugin/plugin.json` — compatibility manifest (`dsh-worker`, skills, `.mcp.json`,
  `requires_local_executor: true`)
- `plugins/dsh-worker/.mcp.json` — stdio server launch with the pinned Python 3.14 interpreter, `${PLUGIN_ROOT}` paths, repo-root env
- `plugins/dsh-worker/requirements.txt` — `mcp>=2.3,<3` runtime dependency
- `plugins/dsh-worker/README.md` — runtime, install, heartbeat, shutdown, registration notes
- `plugins/dsh-worker/runtime/.gitignore` — ignores all job records
- `plugins/dsh-worker/server/dsh_worker_mcp.py` — stdio entry point
- `plugins/dsh-worker/server/plugin_server.py` — six MCP tools, instructions, annotations
- `plugins/dsh-worker/server/core.py` — validation, persistent jobs, workspace lock, status/result/message/cancel
- `plugins/dsh-worker/server/supervisor.py` — hidden detached supervisor, status writer, owned-tree cleanup
- `plugins/dsh-worker/server/heartbeat.py` — actual `dsh-heartbeat-status/1` / `dsh-heartbeat-control/1` integration
- `plugins/dsh-worker/server/procutil.py` — kernel creation-time checks, Windows job object, exact-tree kill
- `plugins/dsh-worker/server/store.py` — atomic JSON/text writes with Windows sharing retries, bounds, job IDs
- `plugins/dsh-worker/server/gitutil.py` — bounded working-tree snapshots for artifact hints
- `plugins/dsh-worker/skills/dsh-worker/SKILL.md` — Codex workflow guidance
- `reality_engine/tests/test_dsh_worker_plugin.py` — 19 offline tests
- `reality_engine/tests/fixtures/dsh_worker_fake_launcher.py` — offline fake launcher/control server
- `.agents/plugins/marketplace.json` — repo-local marketplace entry (no other entries existed)
- This document

No heartbeat-worker-owned file (`run_deepseek_harness.py`, `dsh_heartbeat*`, its tests, its report) was edited.
No STATE/AGENTS/FRAMEWORK/memory/DB/global Codex config was edited. No commits, stashes, pushes, installs.

## Tools

`start_worker`, `worker_status`, `worker_result`, `message_worker`, `cancel_worker`, `list_workers`.

- `start_worker` pins `deepseek-v4.1-flash`, `xhigh`, Go account 2. It accepts exactly one of `brief` or
  `task_file`, a repo-local `workspace`, bounded permission/heartbeat/output/result/timeout settings, and refuses
  peak starts (Mon-Fri 06:30-09:30, 11:30-15:30 IST). The default permission is `read-only` (least privilege);
  Codex must pass `workspace-write` explicitly for implementation. It returns after the supervisor publishes
  initial status, not after the job finishes.
- `worker_status` reads persisted `job.json`/`status.json`/`heartbeat.json` and validates recorded PIDs against
  kernel creation times. It reports `starting`, `running`, `stale`, `cancelled`, `finished`, `failed`, `lost`, or
  `orphaned`. PID liveness alone is never treated as progress.
- `worker_result` returns bounded result text, outcome, artifact hints, limits, and paths. It never returns
  reasoning stderr, the launcher log, or credentials.
- `message_worker` posts to the landed `dsh-heartbeat-control/1` loopback `/ping` endpoint. A transport ack is
  reported with `ack_is_not_a_worker_response: true`; it does not reset or prove worker activity.
- `cancel_worker` requires `confirm=true`, writes a cancel marker, waits for the supervisor, then validates the
  recorded supervisor PID + kernel creation time before killing only that owned tree. It refuses to kill when
  ownership cannot be verified.
- `list_workers` lists persisted jobs, optionally filtered by workspace.

## Persistence and concurrency

Each job gets `runtime/jobs/<timestamp>-<hex>/` with frozen `brief.md`, immutable `job.json`, supervisor
`status.json`, `result.md`, launcher/stream logs, `heartbeat.json`, `result.md.control.json`, baseline snapshot,
and optional `cancel.request`. All JSON writes are atomic with a bounded retry for Windows sharing violations.
The runtime directory is gitignored and defaults to `<repo>/plugins/dsh-worker/runtime` even when Codex installs
the plugin into its cache.

Default policy is one mutating worker per **repository**, enforced by one atomic lock file shared by the root and
all subdirectory workspaces. Read-only jobs do not take the lock and carry a warning that they must not race a
mutating worker. Lock ownership fails closed: timestamps/age do not free it. It is released only when every recorded
supervisor/worker PID is proven dead by kernel creation time (or, for a half-created pre-spawn job, explicitly
forced). A recorded worker still alive keeps the lock even if its supervisor is gone. Corrupt/unreadable locks
block a second writer with explicit inspection/recovery guidance.

The supervisor is spawned hidden with `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, owns the launcher through a
Windows job object with `KILL_ON_JOB_CLOSE`, drains nothing into the MCP protocol, and persists final status.
For mutating jobs, job-object creation and supervisor self-assignment happen before the worker is spawned, and the
worker's membership is verified; if containment cannot be established, the job fails as `containment_unavailable`
instead of running an unowned writer. Closing the MCP session ends the
server; the Codex/MCP host may terminate the server's process tree, which also stops the supervisor/worker. No
unowned writer is left behind; persisted records remain for inspection.

## Heartbeat integration (actual landed interface)

Verified against the concurrent heartbeat worker's landed source/report:

- Status: `--status-file <job>/heartbeat.json`, schema `dsh-heartbeat-status/1`, including
  `dsh_conversation_id`, `provider_routing_session_id`, nested `heartbeat` schedule/misses/pings/activity, and
  `control`.
- Control: `<out>.control.json` = `<job>/result.md.control.json`, schema `dsh-heartbeat-control/1`, with
  `host=127.0.0.1`, ephemeral `port`, `pid`, `run_id`, `session_id`, `state`.
- Ping: `POST /ping` with header `X-DSH-Heartbeat-Token`; body carries `run_id`, `ping_id`, `sequence`,
  `session_id`, and a text-block `message` array. HTTP 200 `{ok, queued, worker_response:false}` is transport
  acceptance only. The landed adapter prefixes every text with `[dsh-heartbeat status check]` and truncates at
  4000 chars, so this is a nudge/defect reminder, not a fresh task; the plugin rejects longer input instead of
  letting the adapter drop text.
- Token: generated per job in the MCP server, passed to the launcher only through the
  `DSH_WORKER_CONTROL_TOKEN` environment variable and `--control-token-env DSH_WORKER_CONTROL_TOKEN`. It is not in
  argv, the manifest, job/status/control files, or logs. It is memory-only; a restarted MCP server cannot
  authenticate existing jobs, `heartbeat.control_token_available` is false, and `message_worker` returns
  `transport_unavailable` rather than reading a secret from disk.
- Capability probe checks the launcher's real `--help`. The launcher must advertise `--heartbeat-interval`,
  `--heartbeat-misses`, `--status-file`, and `--control-token-env`. Missing heartbeat flags refuse with
  `heartbeat_unavailable`; a missing control-token flag refuses with `control_token_unavailable`. There is no
  fallback hard-timeout mode.
- Hard timeout: `hard_timeout_seconds` defaults to `None`. `--timeout` is appended only when the caller explicitly
  supplies a value; omission never adds an 86400s or other implicit duration kill.
- Activity: `worker_status.last_activity_at` comes only from nested `heartbeat.last_activity_at` (committed
  model/tool events) or the supervisor's mirrored `worker_activity_at`. Status/log/heartbeat.json mtimes and
  supervisor poll times are supervision health, not progress, and cannot reset staleness.
- Message bound: the real adapter applies `message.slice(0, 4000)`; the plugin rejects more than 4000 UTF-16
  characters with `message_too_long` and sends nothing, so text is never silently dropped.

Provider routing/cache session (`go_session.session_id`) and actual dsh conversation ID
(`dsh_conversation_id`) are stored and reported separately.

## Checks actually run

```powershell
C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe -m unittest reality_engine.tests.test_dsh_worker_plugin -v
C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe -m unittest reality_engine.tests.test_deepseek_harness_controls reality_engine.tests.test_dsh_heartbeat reality_engine.tests.test_dsh_worker_plugin -v
```

Results:

- Plugin suite: **19 tests passed**. Covers MCP initialize/list_tools/call_tool over real stdio; prompt start;
  partial result; confirmation-gated cancel; cleanup; status/stale/lost; path traversal/outside-root; peak clock;
  concurrency; result bounds; failed-run reasoning exclusion; actual-format loopback control message; wrong
  run/session IDs via the landed `dsh_heartbeat.ControlTransport`; heartbeat flags/status; explicit-only hard
  timeout; missing heartbeat/control capability refusal; over-4000-character nudge rejection; parent/subdirectory
  mutation-lock overlap; fail-closed lock under a live recorded worker; containment fail-closed helper; stale-status
  ignoring mtimes; artifact-hint wording; manifest/layout; server-shutdown no-orphan check.
- Combined heartbeat controls + heartbeat + plugin suite: **50 tests passed** (including the installed-dsh fake-model
  control integration already owned by the heartbeat worker).
- Manifest/marketplace JSON parsed and path rules checked (`./` references, no `..`); no official
  `codex plugin validate` subcommand is exposed in this CLI, so validation is structural plus JSON parsing.
- Offline only: fake launcher, fake loopback control server, local fake-model heartbeat tests; no paid inference,
  no DB.

## Pending / honest limits

1. **Live dsh message smoke not run here.** The message client matches the landed descriptor and `/ping` wire
   contract, is cross-checked with the landed `dsh_heartbeat.ControlTransport`, and is tested against a
   deterministic fake implementing that exact contract. The heartbeat worker separately tested the real `.mjs`
   adapter with installed dsh and a local fake model. Codex should do one bounded live smoke before marking
   `message_worker` fully production-verified.
2. **Token is memory-only.** After an MCP server restart, `worker_status`/`worker_result` still work;
   `heartbeat.control_token_available` reports false and messaging a pre-restart job fails with
   `transport_unavailable`. That is deliberate and documented; no credential-file subsystem was added.
3. **Server shutdown.** The Codex/MCP host may kill the server's process tree, which stops the supervisor and
   worker; the supervisor's job object prevents an unowned worker if the supervisor dies alone. For mutating jobs,
   missing job-object containment is a hard refusal. Do not assume closing the session detaches a job.
4. **Windows-specific ownership.** The kernel creation-time checks, job object, `CREATE_NO_WINDOW`, and
   `taskkill /T` path are Windows-specific; POSIX fallbacks are best-effort only.
5. **Artifact hints are not attribution.** `artifacts.paths` list **newly dirty paths only**; a file already dirty
   at start is omitted even if it changed again, and concurrent edits may appear. Review the full diff.
6. **Real launcher permission is not broadened.** The plugin defaults to `read-only` and passes exactly the
   permission Codex chooses; pass `workspace-write` explicitly for implementation.
7. **Runtime location.** The durable repo-local `plugins/dsh-worker/runtime/` remains the default; it is
   gitignored and survives plugin cache reinstalls. Relocating it under `reality_engine/data/logs/` is optional
   and was not needed for this pass.
8. **One repository lock is intentionally strict.** Mutating workers in unrelated subdirectories of this same
   repository still contend for one lock. That is the chosen one-writer safety policy, not per-subtree parallelism.

## Registration / reload (Codex performs after review)

`.agents/plugins/marketplace.json` is repo-local and already contains only the `dsh-worker` entry:

```json
{
  "name": "local-repo",
  "interface": { "displayName": "Reality Engine Local Plugins" },
  "plugins": [
    {
      "name": "dsh-worker",
      "source": { "source": "local", "path": "./plugins/dsh-worker" },
      "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
      "category": "Productivity"
    }
  ]
}
```

After review, from the repository root:

```powershell
codex plugin marketplace add .
codex plugin marketplace list
codex plugin add dsh-worker@local-repo
```

Use the marketplace's actual top-level `name` if Codex changes `local-repo`. Restart the Codex desktop app/CLI
host so the plugin-provided MCP server is launched. Verify `worker_status` and a rejected peak/path start before
running a real brief. If the repository moves, update `DSH_WORKER_REPO_ROOT` in `plugins/dsh-worker/.mcp.json`
(or set it in the Codex MCP environment); the plugin sources themselves stay `${PLUGIN_ROOT}`-relative.

Do not edit `~/.codex/config.toml`, global marketplaces, or install/register from this worker; that is Codex's
review/install step.
