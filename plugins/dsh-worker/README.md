# dsh-worker — local Codex plugin

Deterministic, desktop-only control plane for DeepSeek/dsh implementation
workers in this repository. It wraps the existing
`reality_engine/scripts/run_deepseek_harness.py`; it does not change the model,
provider route, credentials, or Codex's main model.

## Runtime dependency

- Python 3.14, pinned in `.mcp.json` to
  `C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe`. Do not
  rely on Codex's `PATH`: a bundled Python may not have the MCP dependency.
- `mcp` Python SDK `>=2.3,<3` (declared in `requirements.txt`; verify with the
  pinned interpreter: `<python.exe> -m pip show mcp`)
- PyYAML `>=6,<7` for `jobs.yaml` (also declared in `requirements.txt`)
- Windows job objects, `taskkill` (with a native parent-PID fallback for
  restricted tokens) and DPAPI (`CryptProtectData`, ctypes) for owned-tree
  containment/cancellation and the persisted per-job control token
- Existing dsh installation and the launcher's inherited OpenCode Go account 2
  environment (`OPENCODE_GO_API_KEY_2`). The plugin never reads or writes that
  key; it only passes `--account 2`. Keys stay in the environment, never in this
  manifest or a job record.

Check with the pinned interpreter:

```powershell
C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe -c "import mcp; print('mcp installed')"
```

## Layout

```
plugins/dsh-worker/
  .mcp.json                   stdio MCP launch config
  jobs.yaml                   data-job registry (every job disabled; see below)
  server/                     Python MCP server + detached supervisor
  skills/dsh-worker/SKILL.md  Codex workflow guidance
  runtime/                    gitignored job/status/result records
```

The MCP server is launched with the pinned interpreter as
`<Python314>/python.exe server/dsh_worker_mcp.py` from the plugin root
(`"cwd": "."`). Codex does not expand `${PLUGIN_ROOT}` in a plugin `.mcp.json`;
it appends the literal string to the cache root. Keep startup paths relative to
the plugin root instead. `DSH_WORKER_REPO_ROOT` in `.mcp.json` points at this
checkout because Codex may install the plugin into its cache rather than loading
it in place. If the repository moves, update that environment value (or set it
in the Codex MCP environment).

## Jobs

Each `start_worker` call creates `runtime/jobs/<job_id>/` containing:

- `brief.md` — frozen copy of the complete brief
- `job.json` — immutable job/settings/launcher record
- `status.json` — supervisor-owned mutable status (phase, PIDs, activity, outcome)
- `result.md` — launcher final answer
- `result.md.log` — launcher's local diagnostic/reasoning log (not returned)
- `result.md.events.jsonl` — raw dsh event stream (local evidence, not returned)
- `result.md.control.json` — heartbeat loopback descriptor (no token)
- `heartbeat.json` — `dsh-heartbeat-status/1` supervision record
- `stdout.log`, `stderr.log` — launcher process streams
- `supervisor.log` — supervisor diagnostics
- `progress.jsonl` — model-free supervisor progress digests (one JSON line per
  `progress_interval_seconds`; the last is always written on finish)
- `progress.md` — readable view of the latest digest plus the previous six
- `<workspace>/.tmp/PROGRESS_NOTES.md` — optional worker self-notes (one line per
  milestone; the legacy `<job_dir>/PROGRESS_NOTES.md` is still read)
- `.tmp/` under the workspace (created by the supervisor) — `TMP`/`TEMP`, pip/
  npm/uv caches, worker commit/launch request files; gitignored
- `controller_lease.json` — controller-owned absolute lease (removed on final)
- `control_token.bin` — per-job control token, DPAPI-encrypted for the current
  Windows user (never plaintext, never returned/logged)
- `steering.jsonl` — append-only cross-session audit (who/when/kind, first 200
  characters; never the token)
- `baseline.json` — working-tree snapshot at start
- `cancel.request` — cancellation marker

`status.json` is written atomically under a per-job OS byte-range lock
(`.record.lock`), so concurrent MCP server processes cannot interleave
job-record/lease/steering writes. The MCP server does not keep a private
in-memory registry, so a Codex/Claude restart does not lose jobs. The default
runtime is `<DSH_WORKER_REPO_ROOT>/plugins/dsh-worker/runtime`, so it stays
repo-local even when Codex installs the plugin into its own cache; override it
with `DSH_WORKER_RUNTIME_DIR` only for isolated tests or diagnostics.

Worktree jobs also record `worktree` (path, branch `dsh/<job_id>`, base ref,
base commit), `owner_session`, and `brief_first_line` in `job.json`; the final
status adds `worktree_commit` (head, commits, files changed, whether a commit was
made, or why not).

Artifact hints are deliberately limited: `worker_result.artifacts.paths` lists
**newly dirty paths only** (paths absent from the start snapshot). A file already
dirty at start is excluded even if the worker changed it again, and concurrent
edits may appear. Always inspect the full working-tree diff; the hint is not
attribution.

## Start behavior

`start_worker` pins `deepseek-v4.1-flash`, `max`, account 2, and refuses
Monday-Friday 06:30-09:30 / 11:30-15:30 IST. Exactly one of `brief` or
`task_file` is required. Workspaces must be the repository root or a registered
git worktree of it (arbitrary subdirectories are refused). The default
permission is `read-only` (least privilege); pass `workspace-write` explicitly
for an implementation worker. Exactly one mutating worker per **workspace** is
allowed: the main checkout keeps one lock and every worktree has its own, so
worktree writers can run in parallel while two writers in one checkout still
exclude each other (read-only workers do not take the lock).

`followup_wait_seconds` defaults to `0` (ordinary one-shot exit). A positive
value enables the bounded `agent/turn-stopping` input wait described below.
`controller_lease_seconds` defaults to `1800` and is an independent controller
lease, not a task duration cap (maximum `7200`). `progress_interval_seconds`
defaults to `1200` (20 minutes) and controls the supervisor's model-free
progress digests; `0` disables them (see "Model-free progress digests").

The call returns after the supervisor has published its initial status, not
after the worker finishes. `hard_timeout_seconds` defaults to `None` and no
`--timeout` argument is passed unless you explicitly request one. There is no
automatic duration fallback: if the launcher lacks the required heartbeat or
`--control-token-env` capability, `start_worker` refuses with an actionable
`heartbeat_unavailable` / `control_token_unavailable` error.

## Write scope, temp dir, detached processes

`write_scope` (default `"workspace"`) extends or replaces the dsh sandbox mode;
`permission` still names the dsh mode for the workspace case (dsh 0.2.1 has one
writable root per session, the `--cwd` workspace, and no extra-roots config).

| `write_scope` | dsh mode | confirmation | extra |
|---|---|---|---|
| `workspace` | `permission` as given | — | workspace + `<workspace>/.tmp` |
| `data` | forced `danger-full-access` | `confirm_data_write=true`, non-empty `writes=[...]`, `approved_by` text | `REALITY_DATA_ROOT`, `D:\RealityEngine`; holds `db:<file>` locks for `writes=[...]` |
| `full` | forced `danger-full-access` | `confirm_full_access=true` (Shivam approves first), `approved_by` text | none |

A `data` job must name its DBs: `writes=[]` is refused with `writes_required`
(otherwise it would hold no lock and could write any database). A second `data`
job naming a held DB is refused with `resource_busy` before launch (the manager
writes a start-window reservation and the supervisor holds the OS lock files for
its lifetime, so they cannot go stale). **dsh 0.2.1 makes `data` and `full` the
same access at the OS level** — both run `danger-full-access`; the named locks
and the brief are the real scope, not the sandbox. `write_scope`, `writes`,
`approved_by` and `resource_locks` are recorded in `job.json`, `status.json`,
progress digests, `worker_status` and `list_workers` (`worker_status` prefers
`status.json`, so a hand-edited `job.json` cannot spoof the reported scope).

For every job the supervisor creates `<workspace>/.tmp` and points `TMP`,
`TEMP`, `TMPDIR`, `npm_config_cache`, `PIP_CACHE_DIR`, `UV_CACHE_DIR`,
`PYTHONPYCACHEPREFIX` at it (plus `PIP_DEFAULT_TIMEOUT=120`, `PIP_RETRIES=5`,
`UV_HTTP_TIMEOUT=120`); `.tmp/` is gitignored. Workers install with
`python reality_engine/scripts/setup_worker_env.py` (idempotent, user site;
`--dry-run` reports wheel availability) and may create a per-task
`.venv-<task>` (gitignored).

Long-lived processes are supported only for `write_scope` `data`/`full`: the
worker writes `.tmp/launch.request.json` (`cmd`, optional `log`, `cwd`, `env`)
and the supervisor creates the process via WMI `Win32_Process.Create` (outside
its `KILL_ON_JOB_CLOSE` job), recording `pid`/`log` in `status.detached` and
`.tmp/launch.result.json`. With `workspace` scope the request is refused.
Full details: `tasks/worker_context/SANDBOX.md`.

## Same-conversation follow-ups

`message_worker(kind="status")` keeps the old `/ping` behaviour. With
`kind="followup"` the plugin posts a genuine question to `/followup`. When a
positive `followup_wait_seconds` is configured, the actual dsh
`agent/turn-stopping` hook waits for that follow-up and calls `agent.steer()`
once; the agent loop re-reads its inbox and runs the next step in the same turn
and conversation. There is no shell sleep, no polling model request, and no
duplicate delivery: the endpoint either hands the text to the waiter (which
steers) or steers directly when no wait is active. A timeout or shutdown closes
the turn, so one-shot workers still exit naturally. While waiting,
`worker_status` shows `awaiting_input`, the Python supervisor suppresses idle
heartbeat pings, and `worker_result` can return the latest committed assistant
answer with `interim=true`/`final=false`. The wait is trusted only until its
absolute descriptor deadline.

## Session-independent control (Phase 1)

Every MCP server gets a `session_label`: `DSH_SESSION_LABEL` when set, otherwise
hostname + pid + process start time. Jobs record the session that started or
last claimed them (`owner_session`), and every message, renewal, claim and
cancel appends one line to `job_dir/steering.jsonl`
(`{"at", "session", "kind", "text"}`, text = first 200 characters). A session can
therefore see what other sessions told the worker. `list_workers` rows and
`worker_status` report the owner and the last steerer.

The per-job control token is persisted as `control_token.bin`, DPAPI-encrypted
with **CurrentUser** scope (`CryptProtectData`/`CryptUnprotectData` via ctypes;
no new dependency and no extra path ACL needed because only the same Windows
user can decrypt it). Any dsh-worker MCP server process of that user can
therefore list, message, renew and cancel any job, independent of which session
started it. The plaintext token is never written to a manifest, job record,
status file, steering log, argv or tool response. Jobs created before this
change (or on a host where DPAPI is unavailable) have no token file and report
`control_token_available=false` with
`control_unavailable_reason=control_token_missing`; they remain readable.

`claim_worker(job_id, reason)` explicitly takes lease ownership: it records the
new owner session and the reason in `job.json` and `steering.jsonl`, keeps the
supervisor-validated stable owner id unchanged, and makes later
`renew_worker_lease` calls work without `adopt=true`.

## Controller lease

The MCP server writes `controller_lease.json` with an absolute deadline (default
30 minutes) and a stable owner id. `renew_worker_lease` is the only renewal path
and may extend by at most **7200 seconds (2 hours)**; status/result/list reads,
messaging, model/tool activity, and a restarted MCP server never renew it
automatically. Renewal is allowed for the recorded owner session (the session
that started or claimed the job) or with `adopt=true`. After a restart,
`renew_worker_lease(adopt=true)` takes a still-valid lease over explicitly
(recorded as `adoptions`), and `claim_worker` additionally transfers the
recorded owner session; an expired lease cannot be adopted.
Missing, expired, malformed, wrong-job or wrong-owner leases are refused. The
supervisor checks the lease independently of model activity, kills the verified
owned process tree on expiry, preserves partial output/artifacts, and reports
`controller_lease_expired`. This is deliberate supervision, not a fixed task
duration: a controller can keep renewing productive work.

## Worktree writers

`start_worker(use_worktree=true, base=None)` runs `git worktree add
<DSH_WORKTREES_ROOT>/<job_id> -b dsh/<job_id> <base>` and uses that worktree as
the workspace. `base` defaults to the main checkout's `HEAD`; the resolved base
commit is recorded. `DSH_WORKTREES_ROOT` defaults to the repository's sibling
`IDM-worktrees` directory (on this machine
`C:\Users\warri\Downloads\IDM-worktrees`).

The lock is per workspace path: the main checkout keeps its own lock and each
worktree has its own, so multiple worktree writers run at once. The worker
cannot write `.git/worktrees/<name>` (it is outside the worker sandbox), so the
**supervisor auto-commits** when the worker ends successfully: `git add -A` in
the worktree, author/committer from the repository's git config, subject =
first line of the brief + ` [dsh <job_id>]`, body trailer `DSH-Job: <job_id>`.
An empty diff creates no commit. Failed/cancelled jobs leave their changes
uncommitted for review. A worker that wants its own commit writes
`<workspace>/.tmp/commit.request.json` (`{"message": "..."}`); the supervisor,
which runs unconfined, commits on the next poll, appends the outcome to
`status.worker_commits` (last 50 only) and writes `.tmp/commit.result.json`. This
works for a job-created worktree and for a workspace pointed at an existing
worktree (the linked git dir lives under the main checkout's
`.git/worktrees/<id>` either way); the main checkout itself is refused, and
direct `git commit` inside the job is always blocked by the sandbox. The commit
uses only the `git_dir`/`common_dir`/`toplevel`/`head_ref`/`branch` the manager
captured at job start (`job.json` → `git`), with hooks and fsmonitor disabled
and `--no-verify`, so a worker that rewrites `.git`, points it at another
repository, or ships a fake gitdir with a `pre-commit` hook cannot redirect the
commit or run code; only a `dsh/...` branch is accepted. `worker_status`/
`worker_result` report `worktree.branch`, `base`, `base_commit`, `head`,
`commits`, `files_changed` (and the paths), `committed`, `commit_message` and
any commit error. Main's `HEAD` is never moved by the plugin.

Gitignored data (DBs, indexes) exists only in the main checkout, not in a
worktree. The worker environment gets `REALITY_DATA_ROOT`
(`<repo>/reality_engine/data` by default, overridable with the env var) and the
first line of a worktree brief tells the worker to read it by absolute path and
treat it as read-only.

## Merge queue (Phase 2)

`merge_worker(job_id, target="main", run_tests=true, test_cmd=None)` merges a
finished worktree branch into `target` from the main checkout, holding the
repo-wide merge lock (`runtime/locks/merge-queue.lock`) for the whole
merge+test+rollback. It refuses unless the main checkout is on `target` and has
no unfinished merge. It also refuses when the target working tree has local
changes to files the branch touches (and, more strictly, any unrelated tracked
change, because a rollback uses `reset --hard` and the queue never stashes).

The merge is `git merge --no-ff` with subject `Merge dsh/<job_id> [dsh <job_id>]`
and a `DSH-Job: <job_id>` body trailer. If `mergiraf` is already on `PATH` it is
used as a per-command merge driver (temporary `core.attributesFile` + driver
`-c` config); nothing is installed or configured globally. `run_tests` then runs
`test_cmd`, else the job's declared `test_cmd` (from `start_worker`), else a
compile-only quick suite (`compileall` over `reality_engine`/`plugins`). On a
non-zero test exit the target is reset to its pre-merge `HEAD`; failed test
output tails are returned. On conflict the queue reports the conflicted files
and combined-diff hunk counts, runs `merge --abort`, and verifies the target is
back at its pre-merge `HEAD` with a clean tracked working tree. Nothing is ever
pushed.

`remove_worktree(job_id, delete_branch=false)` removes a finished job's worktree
with a safe `git worktree remove` (a dirty worktree is refused, not forced) and
optionally deletes the branch with `git branch -d` (unmerged branches are
reported). `push(target="main", confirm=false)` refuses unless `confirm=true`;
only pass that on Shivam's explicit go-ahead, and it refuses when `origin` is
not configured.

## Data-job runner (Phase 2)

`plugins/dsh-worker/jobs.yaml` is the shared registry for the recurring data jobs
inventoried in `tasks/DATA_JOBS_AUDIT_2026-10-24.md` (all 57). `DSH_WORKER_JOBS_FILE`
overrides the registry path for isolated tests. Each entry has
name, argv (with `{date}`/`{start}`/`{repo_root}`/`{data_root}` placeholders),
cwd, env, description, writes, named resource locks (`db:<file>`, `gpu`,
`net:<host>`), cadence, a read-only SQL freshness check
(`success_check: {db, sql, expect: {kind: max_date|min_count, ...}}`),
off-peak/market-hours rules, `needs_paid_api`, `needs_gpu`, and `enabled`.
Every job ships `enabled: false` because Shivam disabled the scheduled tasks on
2026-10-21; re-enable only on his word. `start_job` therefore refuses a disabled
job unless `confirm=true` (an explicit one-off), and also refuses paid/off-peak
or market-hours jobs in a restricted window unless confirmed.

`start_job(name, args=None, confirm=False)` runs the argv through the same
supervisor/status/lease/steering machinery as a worker (7200 s lease, owner
session, cancel/renew/claim all work), with no dsh model call, and returns
`run_id` (= job_id). The supervisor takes the named resource locks as OS
byte-range locks for its whole lifetime — a crashed job cannot leave a stale
lock, and a second job needing `db:equity_intelligence.db` or `gpu` is refused
with `resource_busy` (the MCP server probes the locks first to fail fast; the
supervisor re-checks atomically). `list_jobs()` reports each job's enabled state,
latest run and last successful run from the job history, never-ran flag, live
freshness from the SQL check, staleness against cadence, resource locks and
paid/GPU flags. The checks are read-only (`mode=ro`, `PRAGMA query_only`) and
bounded; a slow/locked DB is reported as unverifiable, not as success.
`job_log(run_id_or_name, tail=200)` returns bounded stdout/stderr/supervisor
tails for one run (or the newest run of a job name).

Run data jobs only through these tools: failure classes that exit 0 while
writing nothing (the 2026-10-20 EOD stall) are caught by the freshness check, not
by the exit code. Do not start real fetch/ingest jobs from a test or review
session.

## Heartbeat / message integration

The plugin records and passes the requested heartbeat policy (default `900`
seconds idle, `2` missed replies). It probes the launcher's real `--help`:

- The launcher must advertise `--heartbeat-interval`, `--heartbeat-misses`,
  `--status-file`, and `--control-token-env`; the plugin passes all of them. The
  actual launcher contract is `dsh-heartbeat-status/1` and
  `dsh-heartbeat-control/1`.
- Missing capabilities are a hard refusal. There is no fallback hard-timeout
  mode and no unconditional wall-clock kill.

`message_worker` posts to `/ping` for `kind="status"` or `/followup` for a
genuine same-conversation question, using the actual loopback endpoint from
`result.md.control.json` with `X-DSH-Heartbeat-Token`, `run_id`, `session_id`,
and a text-block `message` array. The per-job token is generated in the MCP
server, passed to the launcher only through the `DSH_WORKER_CONTROL_TOKEN`
environment variable / `--control-token-env`, stored in the job dir only as a
DPAPI blob, and never written to a manifest, job record, status file, control
descriptor, steering log, argv or tool response. A transport acknowledgement is
reported as `ack_is_not_a_worker_response: true`; it does not prove the model
replied.

The status path prefixes every steering text with
`[dsh-heartbeat status check]` and truncates the message at 4000 characters;
the plugin additionally prefixes the delivered status text with
`Status check — answer in one line, then continue your task; this is not the
end of your task.` `message_worker` therefore rejects longer text with
`message_too_long` and sends nothing, so a manual nudge is never silently
shortened. Follow-ups are not wrapped as status checks; they are delivered
through `/followup` and rejected if no wait/running turn can accept them.

`worker_status.last_activity_at` comes from the nested
`heartbeat.last_activity_at` that the dsh supervisor advances only for committed
model/tool events. Status/log/heartbeat file mtimes and supervisor poll times
are not progress. Periodic status writes alone leave a job stale.

Two honest limits:

- The token is persisted DPAPI-encrypted, not memory-only: a restarted MCP
  server of the same Windows user can message, renew (owner/claim/adopt) and
  cancel a job it did not launch. If the job predates the persisted token (or
  DPAPI is unavailable), `message_worker` reports `transport_unavailable`
  rather than reading a plaintext token from disk. `worker_status` still works
  because it does not need the token.
- The message client was verified against the landed `dsh-heartbeat-control/1`
  wire contract with a deterministic fake control server, and the fixture was
  cross-checked with the landed `dsh_heartbeat.ControlTransport` client. A live
  dsh smoke test remains a Codex/reviewer step; this worker did not spend paid
  tokens.

## Progress and visibility (2026-10-22)

`result.md` is streamed by the harness while the worker runs, so a non-empty
file is **not** completion. Use these instead:

- `worker_status.progress.done` is the finished flag (final phase reached).
  `progress.succeeded` = finished with a non-empty answer;
  `progress.answer_empty` = exit 0 but no answer.
- `result_ready` is true only when final *and* non-empty. `result_is_streaming`
  says a running job has partial text so far.
- `progress.summary` is one line, e.g. `running; elapsed 42m; last activity 1m
  ago (tool_call); 37 tool calls, 51 model steps; last tool edit on
  reality_engine/x.py; result.md 3200 B so far (streaming, not final); hard stop
  by 2026-10-22T03:10:00+00:00 (controller_lease_deadline)`.
- `progress.events` holds counts read incrementally from `result.md.events.jsonl`
  (at most 8 MB per call, so a stdout flood never blocks status): tool calls by
  tool, failed tool results, model steps, output tokens, last tool and target,
  last 10 files written/edited. Never thinking text, tool output or shell
  command text.
- `progress.latest_finish_by` is the hard upper bound (lease deadline or
  explicit timeout). dsh gives no completion estimate, so `eta` is always null
  rather than invented.
- `failure_reason` (failed/lost/cancelled jobs) gives the exit code, heartbeat
  failure, the last launcher stderr lines (reasoning lines dropped, token-like
  strings redacted) and a `likely_cause` such as `api_key_env_missing`,
  `dsh_binary_missing`, `peak_hours_refused`, `provider_timeout`.
- `server_info` answers "is the server up": process id, version, start time,
  repo root, launcher capabilities, jobs this process owns.
- `inspect_run(out_file)` gives the same read-only view for a run started with
  the raw `run_deepseek_harness.py` (from its `--out-file`, `.status.json` or
  `.events.jsonl`). PID liveness is checked against the PID's creation time vs
  the run's start, so a recycled PID is reported as `pid_reused`. Such runs
  cannot be messaged, renewed or cancelled from here: their control token lives
  only in the launching process.

`start_worker` also refuses a start within 120 s of a peak window
(`peak_hours_imminent`), and, for the real launcher, refuses up front when the
dsh binary (`dsh_missing`) or `OPENCODE_GO_API_KEY_2` (`api_key_missing`,
presence check only) is absent, instead of launching a job that fails seconds
later. An unreadable `status.json` (e.g. briefly locked by antivirus) is phase
`unknown`, never `lost`.

## Model-free progress digests (2026-10-24)

A `message_worker kind="status"` ping is a turn, not a heartbeat: on
2026-10-24 a worker answered one as its final result and exited early
(`20261024T154434Z-b952dbc2`). Polling `list_workers` from a Claude session is
not enough either — no session means no updates. The **supervisor** now writes
progress itself, with no model call and nothing sent into the worker's
conversation:

- Every `progress_interval_seconds` (start parameter, default `1200` = 20 min;
  `0` disables; `start_worker` and `start_job` both take it) the supervisor
  appends one JSON line to `<job_dir>/progress.jsonl` and rewrites
  `<job_dir>/progress.md` with the latest digest expanded plus the previous six
  entries. A short job gets exactly one digest, written when it finishes, so
  even a five-minute run leaves a real outcome.
- The digest is computed from `result.md.events.jsonl` **incrementally**: the
  scanner remembers its byte offset, so each digest only reads bytes appended
  since the last one (a half-written trailing line waits for the next digest).
  It carries: timestamp, phase, elapsed, tool calls (total, by tool, and the
  delta since the last digest), model steps, output tokens, last tool + target,
  files written since the last digest, idle seconds, lease time left, a stall
  flag (no committed activity for more than 20 minutes), the last three lines
  of the worker's own committed text, and the latest `PROGRESS_NOTES.md` line.
  Thinking text, tool output and shell command text are never included.
- `worker_progress(job_id=None, since=None)` returns those digests newest
  first — all running jobs when `job_id` is omitted — and `list_workers` rows
  gain `last_digest_at` plus a one-line `digest_summary`. `since` accepts an
  ISO-8601 timestamp or a duration like `30m` / `2h`.
- A digest write failure is logged and retried on the next interval; a lost
  update never kills a healthy worker (same rule as the periodic status write).

### Worker self-notes (cooperative, optional)

Every worker brief ends with a standing instruction — never a question to
answer: *"Every ~20 minutes of work, or at each milestone, append one line to
PROGRESS_NOTES.md in your job directory … what's done, what's next, blockers.
Do not stop or wait after writing it."* The absolute path is in the
`DSH_WORKER_PROGRESS_NOTES` environment variable and points at
`<workspace>/.tmp/PROGRESS_NOTES.md` — inside the worker's writable sandbox and
gitignored. The supervisor's digests read the newest line from there and still
fall back to the legacy `<job_dir>/PROGRESS_NOTES.md` (outside the sandbox) for
jobs started before that path moved. The newest note is folded into each digest as
`note`/`worker note`. A worker that ignores it costs nothing: the digests still
come from the event stream.

### Status pings are explicitly non-final

`message_worker kind="status"` keeps the `/ping` transport but now prefixes the
delivered text with
`Status check — answer in one line, then continue your task; this is not the
end of your task.` So a status check can no longer be answered as the final
result. `kind="followup"` is unchanged: a real question, no prefix. The prefix
counts toward the adapter's 4000-character limit, so an over-long status
message is rejected rather than silently truncated.

## Shutdown semantics

The MCP server starts a hidden supervisor and a Windows job object around the
worker. The supervisor is spawned with `CREATE_BREAKAWAY_FROM_JOB` when the
host job object allows it (`survives_server_exit=true` in the start response);
then closing or restarting the MCP server leaves the job running under its
lease, and a restarted/other server claims or adopts it with
`claim_worker(job_id)` / `renew_worker_lease(adopt=true)`. Because the control
token is DPAPI-persisted, that other server can also message and cancel it.
Claude Desktop and the Python MCP client both put children in job objects that
refuse breakaway (verified 2026-10-22, `WinError 5`), so there the start
response says `survives_server_exit=false` with a warning, and the host MCP
client may terminate the server process tree, which also stops the supervisor
and worker.
If the supervisor dies on its own, its job object with `KILL_ON_JOB_CLOSE`
terminates the worker, so no unowned writer survives. For mutating jobs,
job-object creation and supervisor self-assignment happen before the worker is
spawned, and the worker is checked for membership; if containment is
unavailable, the job fails closed instead of running an unowned writer. Persisted job records and
partial results remain under `runtime/jobs/` for inspection after reconnecting.
The workspace mutation lock is retained while a recorded worker is still alive,
even if the supervisor is gone.

Cancellation and heartbeat-stopped cleanup first try `taskkill /T /F` and fall
back to terminating the same parent-PID tree by process handle, which works
even when a restricted agent sandbox token is denied `taskkill`. No broad
image-name kills are used either way.

Do not rely on a closed Codex session to keep a worker alive. Keep the session
open for the duration of a job, or read the persisted status/result after
reconnecting. For deliberate cancellation, use
`cancel_worker(confirm=true)`: it writes a cancel marker, waits for the
supervisor, then validates the recorded PID + kernel creation time before
killing only that owned tree. No broad image-name kills.

## Registration for Claude Code

Register at **user scope** with absolute paths, so the server does not depend on
the Claude session working directory. A project-scoped `.mcp.json` applies only
while Claude treats this repository as the project; on 2026-10-22 a session
whose shell had moved under `plugins/dsh-worker/runtime/jobs/<id>` reported
"MCP server removed from the configuration" twice (cause plausible, not proven).

```powershell
claude mcp add --scope user dsh-worker --env DSH_WORKER_REPO_ROOT=C:/Users/warri/Downloads/Info_Diffusion_Model --env PYTHONUTF8=1 -- C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe C:/Users/warri/Downloads/Info_Diffusion_Model/plugins/dsh-worker/server/dsh_worker_mcp.py
claude mcp get dsh-worker
```

`DSH_WORKER_REPO_ROOT` must be absolute; a relative value is refused
(`repo_root_relative`) because it would resolve against the host cwd. The
server itself works from any cwd (tested from a job directory whose path has a
space and a Devanagari letter). Call `server_info` to confirm which process
answers.

## Registration for Codex (Codex performs this after review)

Do not register globally from this worker. The repo marketplace entry is:

```json
{
  "name": "dsh-worker",
  "source": { "source": "local", "path": "./plugins/dsh-worker" },
  "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
  "category": "Productivity"
}
```

The marketplace root is the repository root, so the path is
`./plugins/dsh-worker` in `.agents/plugins/marketplace.json` (preserve other
entries). Then, after review, Codex can add the local marketplace and install
the plugin:

```powershell
codex plugin marketplace add .
codex plugin marketplace list
codex plugin add dsh-worker@local-repo
```

(Use the actual marketplace `name` if it differs.) Restart the Codex desktop
app/CLI host after adding files or changing `.mcp.json`; plugin-provided MCP
servers are launched by Codex, not by the plugin itself.

## Tests

Offline tests use a fake launcher, fake control server and temporary git
repositories; they do not call DeepSeek or any paid API and never touch the live
`runtime/jobs`. Temporary runtime and worktree directories are created under the
gitignored `plugins/dsh-worker/runtime/test-tmp/` and removed afterwards:

```powershell
python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_dsh_worker_stress -v
```

The integration tests speak real MCP over stdio to separate plugin server
processes. They cover prompt startup, path rejection, concurrency, status/result
persistence, result bounds, cancellation cleanup, DPAPI shared control across
two server processes, claim/renew/steering audit, the two-hour lease cap, the
per-job write race, worktree creation, per-worktree locks, two parallel
worktree writers, supervisor auto-commit on `dsh/<job_id>`, merge success with
tests, rollback on failing tests, a real merge conflict that is aborted cleanly,
dirty/missing target refusal and push refusal, the jobs.yaml inventory/schema,
disabled-job refusal, resource-lock contention, live freshness checks, and one
end-to-end fake data job (`start_job`/`job_log`/`list_jobs`) visible from a
second server process. No real fetch/ingest job is started by the tests.

Progress digests have their own coverage: cadence on a fake clock, incremental
offset resume (append + half-written line, deltas not cumulative totals), the
stall flag, a final digest on finish, `progress_interval_seconds` validation and
`0` disabling, `worker_progress` output shape (newest first, `since`, running
jobs when `job_id` is omitted), `list_workers.last_digest_at`/`digest_summary`,
the appended brief instruction plus `DSH_WORKER_PROGRESS_NOTES`, and the
non-final "Status check —" prefix on `/ping` status pings.
