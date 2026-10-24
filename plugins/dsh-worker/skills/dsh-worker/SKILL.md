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
4. Respect the one-mutating-worker-per-workspace lock. The main checkout and
   each registered git worktree have their own lock, so do not start a second
   writer in the same checkout/worktree (or against the same dsh session).
   Read-only workers do not take the lock but still must not race a mutating
   worker. Arbitrary subdirectories are not workspaces; create a worktree
   instead.
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
  0), `controller_lease_seconds` (default 1800, max 7200), `refresh_context`,
  `progress_interval_seconds` (default 1200; `0` disables the supervisor's
  model-free progress digests), and `use_worktree`/`base` for an isolated
  worktree writer. `write_scope="workspace"` (default) writes the workspace and
  `<workspace>/.tmp` only. `write_scope="data"` additionally approves
  `REALITY_DATA_ROOT` and `D:\RealityEngine` for an approved data job: it needs
  `confirm_data_write=true`, a non-empty `writes=[db files]` (empty is refused
  with `writes_required`) and an `approved_by` text naming who approved it; the
  supervisor holds `db:<file>` locks, and a second job naming a held DB is
  refused `resource_busy` before launch. `write_scope="full"` disables the dsh
  file sandbox and needs `confirm_full_access=true` plus `approved_by` after
  Shivam's approval. dsh 0.2.1 runs data/full the same `danger-full-access` mode
  (one writable root per session), so data is full access at the OS level: only
  the named DB locks and the brief scope it. `worker_status` reports
  `approved_by`; it prefers `status.json`, so editing `job.json` cannot spoof
  the stated scope. Every job gets `<workspace>/.tmp` with `TMP`/`TEMP` and the
  pip/npm/uv caches inside it. The launcher must
  provide the real heartbeat and `--control-token-env` capabilities; the plugin
  refuses to start rather than falling back to a hard timeout. A positive
  `followup_wait_seconds` opts into a bounded host-side wait for explicit
  same-conversation follow-ups; 0 preserves ordinary one-shot exit.
- `worker_status` — read persisted phase, process ownership, heartbeat/session
  state, last activity, `awaiting_input`, controller-lease deadline/remaining
  time, and whether a result is ready. A live PID is not proof of progress.
  `owner_session`/`last_steerer` say which MCP session started/steered it;
  `worktree` reports branch/base/head/commits/files_changed for worktree jobs.
  Report `progress.summary` to the user; `progress.done` is the finished flag.
  `result.md` streams while running, so never treat a non-empty result file as
  done (`result_ready` is only true once final). `progress.events` has tool-call
  counts, the last tool and recent file writes; `progress.latest_finish_by` is
  the hard stop (lease/timeout), and `eta` is deliberately null. Failed jobs
  carry `failure_reason.likely_cause`. Phase `unknown` means the status record
  was momentarily unreadable: poll again, do not treat it as lost. The status
  also reports `write_scope`, `writes`, `write_roots`, `resource_locks`,
  `tmp_dir`, `worker_commits`, `detached`, and the orientation metric
  `tool_calls_before_first_edit` / `orientation_seconds`.
  `stale` means no committed nested heartbeat activity within the configured
  window; a validated deliberate input wait is surfaced as awaiting input, not
  as progress, and a stale/expired wait descriptor stops suppressing checks.
- `worker_progress` — the supervisor's model-free progress digests, newest
  first (`job_id` omitted = all running jobs). Each has timestamp, phase,
  elapsed, tool calls (total/by tool/delta), model steps, output tokens, last
  tool + target, files written since the last digest, idle seconds, lease time
  left, a >20-minute stall flag, the worker's last 3 committed text lines and
  the latest `PROGRESS_NOTES.md` line (`<workspace>/.tmp/PROGRESS_NOTES.md`, the
  `DSH_WORKER_PROGRESS_NOTES` path the brief quotes). Each digest also carries `write_scope`,
  `tool_calls_before_first_edit` and `orientation_seconds` (the orientation
  metric: how many tool calls, and how long, before the first edit/write). Prefer this over pinging a running
  worker; it never touches the worker's conversation. `since` takes an
  ISO-8601 time or `30m`/`2h`.
- `worker_result` — bounded final or partial answer, exit outcome, artifact
  hints, and limits. While a deliberate input wait is active it returns the most
  recent committed assistant answer with `interim=true`, `final=false`; thinking
  and event logs are excluded. Ignore the reasoning log; it is deliberately not
  returned.
- `message_worker` — `kind="status"` (default) posts a status nudge to
  `dsh-heartbeat-control/1` `/ping`; the adapter frames it as
  `[dsh-heartbeat status check]` and the plugin prefixes the delivered text with
  `Status check — answer in one line, then continue your task; this is not the
  end of your task.` `kind="followup"` posts a genuine question to
  `/followup` (no status prefix). If a bounded turn-stopping wait is active the
  question is handed to exactly that waiter and steered once; otherwise a
  running turn accepts a direct steer, and a closing/idle run rejects it. Text
  over 4000 chars is rejected with `message_too_long`, never silently
  shortened. A successful response means transport delivery, not a model
  answer. The per-job control token is persisted DPAPI-encrypted for this
  Windows user, so any dsh-worker MCP server can message a job it did not
  start (legacy token-less jobs return `transport_unavailable`); each delivery
  is recorded in `job_dir/steering.jsonl`.
- `renew_worker_lease` — the only controller-lease renewal path. Explicitly
  extends a running job by at most 7200 seconds (2 hours; default 1800).
  Worker/model activity, status/result/list reads, messaging, and a restarted
  MCP server do not renew it. It works for the recorded owner session, or with
  `adopt=true`. Missing, expired, malformed, wrong-job/wrong-owner leases are
  refused. If the lease expires, the supervisor kills the verified owned tree,
  preserves partial output/artifacts, and reports `controller_lease_expired`
  distinctly. Renew after real review/status, not on a timer.
- `claim_worker` — explicit takeover of a running job's lease ownership,
  recording the new owner session and reason in `job_dir/steering.jsonl`;
  after it, plain `renew_worker_lease` works without `adopt=true`.
- `cancel_worker` — destructive; requires `confirm=true`. It validates the
  recorded supervisor PID and kernel creation time before killing the owned
  process tree. Never kill by image name.
- `list_workers` — inspect persisted jobs, optionally for one workspace
  (repository root or a registered worktree); each row has a one-line
  `summary`, `owner_session`, `last_steerer`, and the newest digest
  (`last_digest_at`/`digest_summary`); corrupt records are listed
  under `unreadable`.
- `merge_worker` — merge a finished worktree job's `dsh/<job_id>` into the
  checked-out target (default `main`) under the repo-wide merge lock, with
  `--no-ff` and a `DSH-Job:` trailer. Refuses a dirty overlapping target,
  wrong checkout or unfinished merge. Runs `test_cmd` (or the job's declared
  command, else a compile-only quick suite); failing tests reset the target to
  its pre-merge HEAD. Conflicts are reported with hunk counts and the target is
  left clean after `merge --abort`. Uses mergiraf only if it is already on
  PATH. Never pushes.
- `remove_worktree` — safely remove a finished job's worktree; a dirty
  worktree is refused, not forced. `delete_branch=true` deletes the merged
  branch with `git branch -d` (unmerged branches are reported).
- `push` — refuses unless `confirm=true`. Only pass `confirm=true` on Shivam's
  explicit go-ahead. Never force-push.
- `list_jobs` — the jobs.yaml registry with enabled state, latest run and last
  success, never-ran flag, live read-only SQL freshness, staleness vs cadence,
  resource locks, paid/GPU flags. Every job ships disabled.
- `start_job` — start one registry job through the same supervisor/status/
  lease/steering machinery, with named `db:`/`gpu`/`net:` resource locks. A
  disabled job needs `confirm=true` (re-enable only on Shivam's word); paid/
  off-peak/market-hours rules also need confirmation outside their window.
  `args` are extra argv entries. Returns `run_id`; use `job_log`.
- `job_log` — bounded stdout/stderr/supervisor tails for a run id, or the
  newest run of a job name.
- `inspect_run` — read-only progress for a run started with the raw harness,
  from its `--out-file` path. It cannot message/renew/cancel such runs.
- `server_info` — confirm the server is up and which process/repo answers.

## Session identities

Keep these distinct:

- **MCP session label** — this server process's identity (`DSH_SESSION_LABEL`,
  else hostname+pid+start). Jobs record `owner_session` and every message,
  renew, claim and cancel in `job_dir/steering.jsonl`, so one Claude/Codex
  session can see what another told the worker.
- **Provider routing/cache session** — the deterministic
  `x-opencode-session` value derived by `go_session.py`. Do not reset it on each
  call; it is not the dsh conversation.
- **dsh conversation ID** — the actual worker conversation identity. It is only
  known when the heartbeat adapter publishes it; `conversation_id_known=false`
  means exactly that.

The provider session may stay stable across a new dsh conversation.

## Shared control across sessions

The per-job control token is persisted DPAPI-encrypted (CurrentUser) in the job
directory, so any dsh-worker MCP server of this Windows user can list, message,
renew and cancel a job started by someone else. The plaintext token is never
logged or returned. Use `claim_worker(job_id, reason)` to take ownership of a
running job deliberately; after that, `renew_worker_lease` works without
`adopt=true`. Legacy jobs with no token file report
`control_token_available=false` (`control_unavailable_reason=control_token_missing`)
and cannot be messaged.

## Worktree writers

Start with `start_worker(..., use_worktree=true, base=<optional git ref>)` to
create `<DSH_WORKTREES_ROOT>/<job_id>` on branch `dsh/<job_id>` from `base`
(default the main checkout's HEAD). Each registered worktree has its own
mutation lock, so several worktree writers can run in parallel; the main
checkout keeps its own lock. On a successful finish the supervisor auto-commits
the worktree (`git add -A`, author from git config, subject
`<brief first line> [dsh <job_id>]`, trailer `DSH-Job: <job_id>`); an empty diff
makes no commit, and failed/cancelled jobs are left uncommitted for review.
`worker_status`/`worker_result` report `worktree.branch`, `base`, `head`,
`commits`, `files_changed`. A worker can commit its own change: write
`<workspace>/.tmp/commit.request.json` with `{"message": "..."}`; the
supervisor commits on its next poll, records `status.worker_commits` (last 50),
and writes `.tmp/commit.result.json`. This covers both a job-created worktree and
a workspace pointed at an existing worktree; the main checkout is refused, and a
direct `git commit` inside a sandboxed job is always blocked (the linked git
dir is outside the writable root). The commit uses only the git identity the
manager captured at job start (never the worker-writable `.git`), runs with
hooks/fsmonitor disabled and `--no-verify`, and refuses a rewritten or
redirected `.git` and any branch other than `dsh/...`. Gitignored data lives
only in the main checkout:
read it from `REALITY_DATA_ROOT` by absolute path, read-only (the one-line
brief preamble says so).

## Merge queue

`merge_worker(job_id, target="main", run_tests=true, test_cmd=None)` merges the
finished worktree branch from the main checkout under a repo-wide merge lock.
It refuses when the checkout is not on `target`, a merge is already in progress,
or the target has local changes to files the branch touches (and any unrelated
tracked change, because rollback is `reset --hard`; the queue never stashes).
Declare the job's tests with `start_worker(..., test_cmd=...)`; otherwise a
compile-only quick suite runs. On failing tests the target is reset to its
pre-merge HEAD; on conflict the queue reports conflicted files and hunk counts,
runs `merge --abort`, and leaves the target clean. Mergiraf is used only when
already on PATH. Never push: `push(target, confirm=true)` only on Shivam's
explicit go-ahead. After a successful merge, `remove_worktree(job_id,
delete_branch=true)` cleans up.

## Data jobs

`jobs.yaml` registers every audited data job (all `enabled: false`; re-enable
only on Shivam's word). `list_jobs` shows run history plus a live read-only SQL
freshness check and cadence staleness, so a job that exits 0 while writing
nothing still shows stale. `start_job(name, args=None, confirm=True)` runs a
disabled job only with `confirm=true`, takes its named db:/gpu/net: resource
locks (refusing `resource_busy`), and uses the same supervisor/status/lease/
steering machinery; `job_log(run_id)` shows the output. Never start a real
fetch/ingest job without Shivam's direction, and never from a test.

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

Every job carries an independent controller lease (default 30 minutes, capped at
7200 seconds / 2 hours per extension), renewed only by an explicit
`renew_worker_lease` call after real review/status. It is not a task duration
cap: productive multi-step/tool work may continue indefinitely while the
controller keeps reviewing and renewing. If Codex/its quota disappears, the
supervisor stops the verified owned tree at the persisted deadline even if the
model is still responsive, preserves partial output/artifacts, and reports
`controller_lease_expired`. Renewal works for the recorded owner session; a
different session must call `claim_worker(job_id, reason)` or
`renew_worker_lease(job_id, adopt=true)` once, deliberately, to take over a
still-valid lease after a restart. Watch `progress.notes`: it warns when the
lease has under 10 minutes left.

## Review loop

1. Poll `worker_status`; do not busy-loop or assume completion from a PID.
2. On completion, read `worker_result`, then inspect the actual working-tree
   diff, files, and tests yourself. Artifact hints list only paths that became
   newly dirty; a file already dirty at start is omitted even if it changed
   again, and concurrent edits may appear. Never treat the hint as attribution.
   For a worktree job, review the committed `dsh/<job_id>` branch and its
   reported `files_changed`; the plugin never merges it.
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
recorded worker that is still alive keeps its workspace mutation lock even when
the supervisor is gone, so inspect before retrying. Persisted job records remain
for inspection, and another MCP server of this Windows user can claim/message/
cancel them. Keep the Codex session open for a job that must finish; do not
assume closing the session detaches it. Use `cancel_worker(confirm=true)` when
you deliberately want to stop work. The runtime directory is repo-local and
gitignored.
