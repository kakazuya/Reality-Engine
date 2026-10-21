---
name: dsh-worker
description: Start, inspect, message, and cancel deterministic local DeepSeek/dsh implementation workers in this repository. Use when Codex needs an off-peak DeepSeek worker with full context, persisted results, and an honest process/heartbeat status instead of hand-built PowerShell calls.
---

# dsh-worker

Use this skill for off-peak DeepSeek implementation work. The plugin is a thin,
deterministic control plane over `reality_engine/scripts/run_deepseek_harness.py`;
it does not replace the launcher, change Codex's model, or add a provider route.

## Before starting

1. Read the authority files relevant to the task (`tasks/FRAMEWORK.md`,
   `tasks/STATE.md`, `tasks/codex_tasks/WORKING_PROTOCOL.md`) and put the
   complete task, constraints, allowed files, and verification expectations in
   the brief or a repo-local task file. The worker cannot see this chat.
2. Check that it is off-peak yourself: peak is Monday-Friday 06:30-09:30 and
   11:30-15:30 IST. `start_worker` refuses those windows.
3. Choose the narrowest sufficient `permission` (`read-only`,
   `workspace-write`, or `danger-full-access`). The default is `read-only`;
   pass `workspace-write` explicitly for an implementation worker. Do not
   broaden it without a reason.
4. Respect the one-mutating-worker-per-repository lock. The lock covers the
   repo root and every subdirectory, so do not start a second writer in any
   checkout path or against the same session. Read-only workers do not take the
   lock but still must not race a mutating worker.
5. Never put API keys, tokens, auth-file contents, or other secrets in a brief,
   task file, status record, or tool argument. The launcher obtains credentials
   from inherited/user environment.

## Tools

- `start_worker` — pass exactly one of `brief` or `task_file`. It returns
  promptly with `job_id`, `status_path`, `result_path`, and warnings. It pins
  `deepseek-v4.1-flash`, max, Go account 2. Optional settings are bounded:
  `heartbeat_interval_seconds` (default 900), `missed_replies` (default 2),
  `max_output_tokens`, `max_result_bytes`, optional `hard_timeout_seconds`
  (default `None`; omit for pure heartbeat supervision, or pass an explicit
  value for a deliberate wall-clock cutoff), `followup_wait_seconds` (default
  0), `controller_lease_seconds` (default 1800), and `refresh_context`. The
  launcher must provide the real heartbeat and `--control-token-env`
  capabilities; the plugin refuses to start rather than falling back to a hard
  timeout. A positive `followup_wait_seconds` opts into a bounded host-side
  wait for explicit same-conversation follow-ups; 0 preserves ordinary
  one-shot exit.
- `worker_status` — read persisted phase, process ownership, heartbeat/session
  state, last activity, `awaiting_input`, controller-lease deadline/remaining
  time, and whether a result is ready. A live PID is not proof of progress.
  Report `progress.summary` to the user; `progress.done` is the finished flag.
  `result.md` streams while running, so never treat a non-empty result file as
  done (`result_ready` is only true once final). `progress.events` has tool-call
  counts, the last tool and recent file writes; `progress.latest_finish_by` is
  the hard stop (lease/timeout), and `eta` is deliberately null. Failed jobs
  carry `failure_reason.likely_cause`. Phase `unknown` means the status record
  was momentarily unreadable: poll again, do not treat it as lost.
  `stale` means no committed nested heartbeat activity within the configured
  window; a validated deliberate input wait is surfaced as awaiting input, not
  as progress, and a stale/expired wait descriptor stops suppressing checks.
- `worker_result` — bounded final or partial answer, exit outcome, artifact
  hints, and limits. While a deliberate input wait is active it returns the most
  recent committed assistant answer with `interim=true`, `final=false`; thinking
  and event logs are excluded. Ignore the reasoning log; it is deliberately not
  returned.
- `message_worker` — `kind="status"` (default) posts a status nudge to
  `dsh-heartbeat-control/1` `/ping`; the adapter frames it as
  `[dsh-heartbeat status check]`. `kind="followup"` posts a genuine question to
  `/followup` (no status prefix). If a bounded turn-stopping wait is active the
  question is handed to exactly that waiter and steered once; otherwise a
  running turn accepts a direct steer, and a closing/idle run rejects it. Text
  over 4000 chars is rejected with `message_too_long`, never silently
  shortened. A successful response means transport delivery, not a model
  answer. If the adapter/token is unavailable (including after an MCP restart)
  the tool returns `transport_unavailable` rather than pretending stdin append
  works.
- `renew_worker_lease` — the only controller-lease renewal path. Explicitly
  extends a running job by at most 30 minutes (default 1800s). Worker/model
  activity, status/result/list reads, messaging, and a restarted MCP server do
  not renew it. Missing, expired, malformed, wrong-job/wrong-owner leases are
  refused. If the lease expires, the supervisor kills the verified owned tree,
  preserves partial output/artifacts, and reports `controller_lease_expired`
  distinctly. The default lease is 30 minutes; renew after real review/status,
  not on a timer.
- `cancel_worker` — destructive; requires `confirm=true`. It validates the
  recorded supervisor PID and kernel creation time before killing the owned
  process tree. Never kill by image name.
- `list_workers` — inspect persisted jobs, optionally for one workspace; each row
  has a one-line `summary`; corrupt records are listed under `unreadable`.
- `inspect_run` — read-only progress for a run started with the raw harness,
  from its `--out-file` path. It cannot message/renew/cancel such runs.
- `server_info` — confirm the server is up and which process/repo answers.

## Session identities

Keep these distinct:

- **Provider routing/cache session** — the deterministic
  `x-opencode-session` value derived by `go_session.py`. Do not reset it on each
  call; it is not the dsh conversation.
- **dsh conversation ID** — the actual worker conversation identity. It is only
  known when the heartbeat adapter publishes it; `conversation_id_known=false`
  means exactly that.

The provider session may stay stable across a new dsh conversation.

## Same-conversation follow-ups

Start once with `followup_wait_seconds` set (for example 60-300) when several
questions must arrive sequentially in one live dsh conversation. After each
answer the shipped control plugin uses the supported awaited
`agent/turn-stopping` hook to wait without a shell sleep, polling model request,
or status prompt. Poll `worker_status` for `awaiting_input` (do not busy-loop),
read the interim `worker_result` if useful, then call `message_worker` with
`kind="followup"`. Each question is steered exactly once in the same
conversation; the next model request is the answer to that question. When the
bounded wait expires the turn closes and a one-shot worker exits normally. This
is opt-in: leave `followup_wait_seconds` at 0 for ordinary one-shot work.

## Controller lease

Every job carries an independent 30-minute controller lease, renewed only by an
explicit `renew_worker_lease` call after real review/status. It is not a task
duration cap: productive multi-step/tool work may continue indefinitely while
the controller keeps reviewing and renewing. If Codex/its quota disappears, the
supervisor stops the verified owned tree at the persisted deadline even if the
model is still responsive, preserves partial output/artifacts, and reports
`controller_lease_expired`. Renewal authority is memory-only, so a restarted
MCP server never extends a deadline implicitly; call
`renew_worker_lease(job_id, adopt=true)` once, deliberately, to take over a
still-valid lease after a restart. Watch `progress.notes`: it warns when the
lease has under 10 minutes left.

## Review loop

1. Poll `worker_status`; do not busy-loop or assume completion from a PID.
2. On completion, read `worker_result`, then inspect the actual working-tree
   diff, files, and tests yourself. Artifact hints list only paths that became
   newly dirty; a file already dirty at start is omitted even if it changed
   again, and concurrent edits may appear. Never treat the hint as attribution.
3. Send concrete defects back with a real `message_worker` follow-up when the
   heartbeat adapter is available. Otherwise report the pending transport seam
   or start a fresh job with the new context; do not fake a message.
4. Preserve working files and unrelated local changes. Do not commit, stash,
   push, delete, or rewrite state outside the worker's allowed files.
5. Do not automatically retry paid work. A failed/truncated run is handed back
   with its actual outcome and limits.

## Shutdown and cancellation

Closing the MCP session ends the plugin server. If the start response says
`survives_server_exit=false` (Claude Desktop and Python MCP hosts refuse job
breakaway), the host may terminate the server's process tree, which also stops
the supervisor and worker. The
supervisor's own Windows job object prevents an unowned worker if the supervisor
dies alone; mutating jobs fail closed if containment cannot be established. A
recorded worker that is still alive keeps the repository mutation lock even when
the supervisor is gone, so inspect before retrying. Persisted job records remain
for inspection. Keep the Codex session open for a job that must finish; do not
assume closing the session detaches it. Use `cancel_worker(confirm=true)` when
you deliberately want to stop work. The runtime directory is repo-local and
gitignored.
