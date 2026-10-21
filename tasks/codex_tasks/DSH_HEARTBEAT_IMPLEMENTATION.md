# DSH heartbeat supervision — implementation

Date: 2026-10-21. Scope: `run_deepseek_harness.py` and narrowly named heartbeat support. No vendor package,
database, H01, Telegram, or plugin-packaging file was edited.

## Files changed

- `reality_engine/scripts/run_deepseek_harness.py` — default heartbeat mode, optional explicit hard timeout,
  local control-plugin patch, streamed supervision, status/control/evidence paths.
- `reality_engine/scripts/dsh_heartbeat.py` — deterministic state machine, JSON event parser, loopback control
  transport, pipe drainers, process/status writer, partial-output preservation.
- `reality_engine/scripts/dsh_heartbeat_control.mjs` — per-invocation Cordis plugin that binds the same live agent
  and calls `Agent.steer()` for status requests.
- `reality_engine/tests/test_deepseek_harness_controls.py` — heartbeat patch/no-secret checks.
- `reality_engine/tests/test_dsh_heartbeat.py` — fake clock/transport/worker tests and an installed-dsh local
  integration test using a fake OpenAI-compatible model server.
- This document.

## Schedule and semantics

Defaults are exactly the requested heartbeat:

| Event | Default |
|---|---|
| No committed worker activity for | 900 s |
| Then send status request 1 | immediately |
| Wait for real activity | 900 s |
| No response: miss 1, send status request 2 | immediately |
| Wait for real activity | 900 s |
| No response: miss 2, stop and report failure | exit 125 |

Any real committed worker activity resets the consecutive-miss count and the idle timer. The two status requests are
not sent at fixed 15/30-minute wall-clock marks; they are relative to the last real activity. A productive worker can
run indefinitely without being killed.

`--timeout N` is now an **optional explicit hard wall-clock cutoff** (exit 124) for probes/troubleshooting. It is
separate from the heartbeat and wins if it fires. Omitting `--timeout` no longer means "kill at 900 s". Existing callers
that pass `--timeout 100` keep the old hard-cutoff behavior.

### What counts as worker activity

Only committed worker events reset the miss count:

- assistant `text` or `thinking` content;
- `tool_call` and `tool_result`;
- a `final` answer;
- a `step_end` carrying nonzero output tokens.

Not activity: timer ticks, supervisor pings, HTTP 200/`queued` acknowledgements, a `step_start`/`turn_start`
caused by the ping, or PID/CPU liveness. A transport acknowledgement is explicitly returned with
`worker_response: false` and does not reset anything.

A ping is queued with `Agent.steer()`, so it is consumed at the next model/tool boundary. It does not cancel an
in-flight reasoning call. If the worker is idle, `steer` wakes it.

## Same-agent transport

`dsh-headless` reads its task from stdin once; appending to stdin is not a control channel. The wrapper therefore
loads `dsh_heartbeat_control.mjs` through a temporary `--patch` insert using a `file:///...` module name. The plugin:

1. starts an HTTP server on `127.0.0.1` with an ephemeral port;
2. binds the first runtime-root agent (`ctx.agents.roots()` and `agent/created`);
3. writes `<out-file>.control.json` (`dsh-heartbeat-control/1`) with host, port, PID, run id, session id, state;
4. accepts an authenticated `POST /ping` and calls `agent.steer({content:[...], source:{kind:"dsh-heartbeat"}})`.
5. calls `server.unref()` so the listener cannot keep the one-shot process alive, and closes it on Cordis disposal.

Security properties:

- loopback bind only; no remote interface;
- per-run 256-bit token from `DSH_HEARTBEAT_TOKEN`, compared with `crypto.timingSafeEqual`;
- the token is **not** written to the patch, status file, control descriptor, or logs;
- `run_id` and optional `session_id` must match the bound run/agent;
- browser `Origin` headers are rejected; only `POST /ping` (and a token-protected `GET /health`) are served;
- request bodies are capped at 64 KiB;
- the descriptor file contains no secret;
- the process is killed as a tree on stop, then the wrapper checks the port is closed.

A parent orchestrator that needs to send its own supported pings can supply the same token through
`--control-token-env NAME` (the named env var must contain at least 32 characters). It can read host/port/session
from `<out>.control.json` and use the token it already owns. Without that flag the wrapper generates the token and only
the wrapper (and the child process environment) knows it.

The local control contract for an external caller is:

```
POST http://127.0.0.1:<port>/ping
X-DSH-Heartbeat-Token: <per-run token>
Content-Type: application/json

{"run_id":"<control.run_id>","ping_id":"...","sequence":1,
 "session_id":"<control.session_id>",
 "message":[{"type":"text","text":"status request"}]}
```

A successful response is `{"ok":true,"queued":true,"worker_response":false,...}`. The HTTP 200/queued result means the
steering item entered the same agent's inbox; it is **not** proof that the model responded.

## Outputs and status record

For `--out-file X`:

| Path | Content |
|---|---|
| `X` | final answer on success; partial assistant text on a failed/interrupted run |
| `X.log` | metadata header, dsh stderr, reasoning text, heartbeat ping/miss/stop lines |
| `X.status.json` | machine-readable supervision/session record |
| `X.control.json` | local control descriptor (host/port/session; **no token**) |
| `X.events.jsonl` | raw dsh `--json` event stream for local audit/replay |

`X.status.json` uses schema `dsh-heartbeat-status/1`. Important fields:

- `run_id`, `state`, `exit_code`, `failure`, `failure_detail`, `partial`, `final_event`;
- `started_at`, `ended_at`, `duration_seconds`, `pid`;
- `model`, `reasoning_effort`, `account`, `permission`, `cwd`;
- `dsh_conversation_id` (exact dsh session id) and `provider_routing_session_id`
  (stable `x-opencode-session` header; a different identity);
- `control` (`schema`, `host`, `port`, `endpoint_file`, `session_id`, `listener_closed`);
- `heartbeat` (schedule, current idle, consecutive misses, ping records with delivery/answer/miss outcome,
  bounded recent activity events; no reasoning text);
- `counters` and `stderr_tail`;
- `outputs` paths.

The status writer uses atomic replace and throttles writes to at most about five per second; ping/miss/final writes
are forced.

## Flags

```
--timeout SECONDS                 explicit hard cutoff (exit 124); omitted = no hard cutoff
--heartbeat-interval SECONDS      idle threshold before a ping (default 900)
--heartbeat-response-window SEC   wait for real activity after a ping (default 900)
--heartbeat-misses N              consecutive unanswered pings before stop, 2-10 (default 2)
--status-file PATH                override the default <out>.status.json
--control-token-env NAME          use a parent-owned token from this env var (default: generate one)
```

Exit codes: `0` completed with a final answer, `1` dsh failure/missing or empty final/non-completed turn,
`124` explicit hard timeout, `125` heartbeat stopped after two unanswered requests, `126` control channel could not be
established, `2` argparse usage error.

## Tests actually run

```
python -m unittest reality_engine.tests.test_deepseek_harness_controls reality_engine.tests.test_dsh_heartbeat -v
```

Result: **31 tests passed**. Coverage includes:

- healthy long run across many idle intervals with zero pings;
- exact two-unanswered schedule and exit 125;
- queued HTTP 200 acknowledgement alone does **not** reset misses;
- real activity after a ping resets misses;
- delivery-failure classification;
- explicit hard timeout, including before control readiness;
- fake-worker process integration: pipe drain, partial output, early failure, control-not-ready, listener cleanup,
  stale control-descriptor rejection, missing-final and non-completed-turn non-success;
- file/status/control/log token-absence check;
- parent-supplied control token validation;
- actual installed dsh + actual `.mjs` plugin + local fake OpenAI-compatible SSE model: the model receives the
  `[dsh-heartbeat status check]` steering message, the run completes, and the listener is closed;
- the full `run_supervised()` against actual dsh reports `pings[0].outcome == "answered"` and writes the final answer.

Also run: `python -m py_compile` on both Python files and `node --check` on the plugin. No live/paid inference was
called.

## Limitations and remaining limits

- Headless remains one-shot. The control mechanism drives the same live process; it is not durable multi-turn
  persistence and does not resume a dead process. If dsh exits before a ping can be delivered, the wrapper reports
  the dsh outcome rather than pretending a response occurred.
- A status nudge is a user-role steering message. The model decides how to respond; it may acknowledge and stop, or
  continue working. The supervisor cannot force continuation, and if the process exits the run ends.
- `steer` is consumed at the next step boundary. A single silent model or tool call longer than two response windows
  will still be stopped, even if it later returns. That is the specified two-unanswered-request behavior; a tool that
  streams no committed event is indistinguishable from silence to the supervisor.
- The control token is available only to the launching process/child environment. A separate process must be given
  it explicitly (`--control-token-env`); reading the status/control files does not reveal it.
- If the plugin fails to load, the wrapper waits up to 30 s for control readiness, then kills and exits 126. The
  dsh stderr log contains the plugin load error.
- The raw `.events.jsonl` and `.log` are local evidence and may contain reasoning, tool output, or task text; they are
  not printed to the wrapper's Codex-facing stdout and should be handled as sensitive local files.
- Windows process-tree cleanup uses `taskkill /T /F`; the POSIX fallback is SIGTERM to the process only.
- The installed-dsh integration test is skipped when `dsh` is absent. All other tests are local and deterministic.
- No plugin-packaging, state, framework, H01, or vendor files were changed.
