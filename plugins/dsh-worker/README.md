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
lease, not a task duration cap (maximum `7200`).

The call returns after the supervisor has published its initial status, not
after the worker finishes. `hard_timeout_seconds` defaults to `None` and no
`--timeout` argument is passed unless you explicitly request one. There is no
automatic duration fallback: if the launcher lacks the required heartbeat or
`--control-token-env` capability, `start_worker` refuses with an actionable
`heartbeat_unavailable` / `control_token_unavailable` error.

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
uncommitted for review. `worker_status`/`worker_result` report
`worktree.branch`, `base`, `base_commit`, `head`, `commits`, `files_changed`
(and the paths), `committed`, `commit_message` and any commit error. Main's
`HEAD` is never moved by the plugin.

Gitignored data (DBs, indexes) exists only in the main checkout, not in a
worktree. The worker environment gets `REALITY_DATA_ROOT`
(`<repo>/reality_engine/data` by default, overridable with the env var) and the
first line of a worktree brief tells the worker to read it by absolute path and
treat it as read-only.

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
`[dsh-heartbeat status check]` and truncates the message at 4000 characters.
`message_worker` therefore rejects longer text with `message_too_long` and sends
nothing, so a manual nudge is never silently shortened. Follow-ups are not
wrapped as status checks; they are delivered through `/followup` and rejected
if no wait/running turn can accept them.

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
worktree writers, and supervisor auto-commit on `dsh/<job_id>`.
