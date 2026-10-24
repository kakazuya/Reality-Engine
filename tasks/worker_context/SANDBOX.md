# Worker sandbox, temp, write scopes and detached processes

Written 2026-10-25 (Task 03) from the live dsh 0.2.1 sources and the two profile
patches. Read this before starting a worker that needs to install packages,
write outside the worktree, commit, or launch something long-lived.

## 1. What `permission` actually does (verified mapping)

`start_worker(permission=...)` → `run_deepseek_harness.py --permission` → the
launcher sets `DSH_PERMISSION_MODE` → `dsh-base/cordis.patch.yml` reads it in two
rows:

| `permission` | `dsh-sandbox-policy.mode` | `dsh-user-approval.policy` | Effect |
|---|---|---|---|
| `read-only` | `read-only` | `ask` | No write grants. Confined pwsh gets no private temp either, so `tempfile.mkdtemp()` fails. |
| `workspace-write` (default for mutating jobs) | `workspace-write` | `ask` | Writes under the session cwd (the `--cwd` workspace) plus a per-session private temp dir; `dsh-pwsh-sandbox` rewrites `TMP`/`TEMP` to that private dir for every confined command. |
| `danger-full-access` | `danger-full-access` | `never` | No confinement; the sandbox provider is never consulted. |

Key facts:

- The **writable root is the session cwd**, i.e. the `--cwd` passed to dsh
  (`workspace` / the worktree). `sandbox-policy.workspaceRoot` is only a
  fallback for calls without a session cwd.
- Windows enforcement is the **ACL restricted-token rung**
  (`dsh-sandbox-windows-acl`): a `WRITE_RESTRICTED` token whose restricting SIDs
  carry the workspace SID (deterministic per workspace path) and a random
  per-session temp SID, lowered to Low integrity. It is reported as `partial`
  (hard links alias file objects, reads are unconfined).
- **There is no extra-writable-roots setting in dsh 0.2.1.** One writable root
  per session; the fs fence (`dsh-fs-sandbox`) and the pwsh runner both derive
  their roots from the same policy. A junction/symlink inside the workspace to
  `reality_engine/data` does not help: both the fence and the ACL token check the
  resolved target.
- The fs fence (`dsh-fs-sandbox`) also allows `os.tmpdir()` in
  `workspace-write`, but the confined pwsh child is the stricter boundary.

## 2. Per-job temp and caches (supervisor)

For every job the supervisor creates `<workspace>/.tmp/` and exports to the
worker process:

| Variable | Value |
|---|---|
| `TMP`, `TEMP`, `TMPDIR` | `<workspace>/.tmp` |
| `npm_config_cache` | `<workspace>/.tmp/npm-cache` |
| `PIP_CACHE_DIR` | `<workspace>/.tmp/pip-cache` |
| `UV_CACHE_DIR` | `<workspace>/.tmp/uv-cache` |
| `PYTHONPYCACHEPREFIX` | `<workspace>/.tmp/pycache` |
| `PIP_DEFAULT_TIMEOUT`, `PIP_RETRIES` | `120`, `5` |
| `UV_HTTP_TIMEOUT` | `120` |

`.tmp/` is gitignored (root `.gitignore`). Use it for `tempfile`, `pip install
--target .tmp/x ...`, `npx`, and scratch outputs; never write to the ambient
`%LOCALAPPDATA%\Temp` (denied under `read-only`, unlabelled under
`workspace-write`). `tempfile.mkdtemp()` works because `TMP` now points into the
workspace; inside a confined pwsh it points at the sandbox's private temp (also
writable).

Two sandbox facts drive the rest of the setup:

- The supervisor prepends `plugins/dsh-worker/worker_bootstrap` to the worker's
  `PYTHONPATH` and sets `DSH_WORKER_SANDBOXED=1` only for file-sandboxed jobs
  (`read-only`/`workspace-write`; never `danger-full-access`). Its
  `sitecustomize` drops Python 3.14's explicit `0o700` DACL when creating temp
  directories only when that marker is present: under the write-restricted
  token that DACL cuts off the inherited workspace capability, so
  `tempfile.mkdtemp()` could create a directory but not write inside it
  (`python -S`` bypasses this, and an ordinary Python process is never patched).
- `DSH_WORKER_PROGRESS_NOTES` points at `<workspace>/.tmp/PROGRESS_NOTES.md`,
  not the job directory (outside the sandbox). Digests read the new path first
  and fall back to the legacy `<job_dir>/PROGRESS_NOTES.md`.

`.tmp/` is also the supervisor's request channel (below). The worker can write
there under `workspace-write`.

## 3. Write scopes (`start_worker(write_scope=...)`)

| `write_scope` | dsh mode used | Confirmation | Extra authority |
|---|---|---|---|
| `workspace` (default) | the requested `permission` | — | workspace + `.tmp` only |
| `data` | forced `danger-full-access` | `confirm_data_write=true` + `writes=[...]` + `approved_by` text | `REALITY_DATA_ROOT` (`reality_engine/data`) and `D:\RealityEngine`; the supervisor holds `db:<file>` locks for each entry in `writes=[...]` |
| `full` | forced `danger-full-access` | `confirm_full_access=true` (Shivam approves first) + `approved_by` text | no file restriction |

**dsh 0.2.1 makes `data` == `full` access at the OS level.** Because the dsh
sandbox has one writable root per session and no extra-roots setting, a `data`
job runs the same `danger-full-access` mode as a `full` job: nothing at the OS
level stops it writing any file. The difference is process policy, not
enforcement — the brief's write roots, the named `db:<file>` locks and the human
approval. Treat `write_scope='data'` as full access that happens to be briefed
to touch only the named DBs.

`writes=[...]` is required for `data`: it accepts bare file names with or
without a `db:` prefix (`["equity_intelligence.db"]`), and a `data` job with an
empty list is refused with `writes_required` (it would hold no lock and could
write every DB). A non-`data` job that passes `writes` is refused with
`writes_requires_data_scope`. `approved_by` records who approved a `data`/`full`
job in `job.json`, `status.json` and `worker_status`; `confirm_*` is only the
caller's own flag, so the approval text is the audit trail. The manager writes a
start-window reservation for each named lock before it spawns the supervisor
(the supervisor removes it after taking the real OS lock), so a simultaneous
second start is refused with `resource_busy` before anything is launched.

`write_scope` is recorded in `job.json`, `status.json`, every progress digest,
`worker_status` and `list_workers`. `worker_status` prefers `status.json`: the
job record sits in a directory a worker could reach when its workspace is the
main checkout, so a hand-edited `job.json` scope does not change the reported
scope (and never changed the launch decision).

Never start a `data` job unless the brief is approved to write there. Never use
`full` without Shivam's explicit go-ahead.

## 4. Committing from a worktree job

The worktree index/objects live in the main checkout's
`.git/worktrees/<id>`, outside the sandbox's writable root, so `git commit`
inside the job is denied. Supported path:

1. The worker writes `<workspace>/.tmp/commit.request.json` with
   `{"message": "feat: ..."}` (its own `write` tool).
2. The supervisor (unconfined) runs the commit on the next ~2 s poll, appends
   the result to `status.worker_commits` (last 50 only), and writes
   `<workspace>/.tmp/commit.result.json` (`{"ok": true, "commit": {...}}`).
3. Works for a job-created worktree **and** for a workspace pointed at an
   existing worktree. Direct `git add`/`git commit` inside the job cannot work
   in either case: the index/refs live under `<main>/.git/worktrees/<id>`,
   outside the writable root, so use the request file. The supervisor's
   end-of-run auto-commit still runs and creates no second commit when the tree
   is clean.

The commit never trusts the worktree's `.git`. When the job starts, the manager
(outside the sandbox) records the real `git_dir`, `common_dir`, `toplevel`,
`head_ref` and `branch` in `job.json` (`job["git"]`). The supervisor then runs:

```
git --git-dir=<stored git_dir> --work-tree=<stored toplevel> \
    -c core.hooksPath=NUL -c core.fsmonitor=false \
    -c core.sshCommand= -c diff.external= \
    add -A                      # then
    commit --no-verify -m ...   # only on refs/heads/dsh/...
```

It refuses when the stored common dir is not `<repo>/.git`, when the stored git
dir is the main checkout's own `.git` (the main checkout is never a worker
commit target), when `<workspace>/.git` no longer points at the stored git dir
(worker-owned fake gitdir / redirect to another repository), or when HEAD is not
a `refs/heads/dsh/...` branch (or the recorded branch). So a worker that
rewrites `.git` cannot run its own `pre-commit` hook or commit into another
repository, and the request file can never supply git `-c` options.

## 5. Detached long-running processes (`write_scope` data/full only)

A child of a confined shell dies with it, and the supervisor holds a
`KILL_ON_JOB_CLOSE` job object, so a normal background child dies too. The
supported escape is WMI: the supervisor runs `Invoke-CimMethod Win32_Process
Create`, so WmiPrvSE — not the worker or the supervisor — is the parent.

Worker protocol: write `<workspace>/.tmp/launch.request.json`:

```json
{
  "cmd": "python -m reality_engine.scripts.some_job --flag",
  "log": ".tmp/some-job.log",
  "cwd": ".",
  "env": {"REALITY_DATA_ROOT": "C:/Users/warri/Downloads/Info_Diffusion_Model/reality_engine/data"}
}
```

- `cmd` is a string or an argv list; it runs through `cmd.exe /c` (a `.cmd`
  wrapper is generated under `.tmp`).
- `log` and `cwd` must resolve inside `.tmp`, the workspace, `REALITY_DATA_ROOT`
  or `D:\RealityEngine`; the default log is `.tmp/detached-<ts>.log`.
- Optional `env` is written as `set` lines into the wrapper (WMI-created
  processes do not inherit the worker's environment — Winmgmt's environment is
  the parent — so pass absolute interpreter paths or an explicit `PATH`).
- The supervisor writes `.tmp/launch.result.json` with `ok`, `pid`, `log`, and
  records `pid`/`command`/`log` in `status.detached` (the job record view).
- Refused unless `write_scope` is `data` or `full`
  (`launch_detached_requires_write_scope_data_or_full`).

## 5a. Testing the sandbox from inside a sandbox

A nested sandbox cannot be created from an already-confined token: the runner's
`SetNamedSecurityInfoW` fails with Win32 5 (our token has no `WRITE_DAC`) and
`CreateRestrictedToken` fails with Win32 87 when the caller is already
write-restricted. Run end-to-end sandbox demos from Claude's unconfined shell,
from a supervisor-launched worker, or (as Task 03 did) exercise the same
workspace-write token that the session already holds. The Task 03 probe is
`tasks/worker_context/sandbox_probe.py` (its docstring has the exact command).

## 6. Dependencies and per-task venvs

- `requirements-worker.txt` (repo root): pymupdf, pyyaml, requests, numpy,
  pandas, duckdb, openpyxl, xlrd. All have a cp314/abi3 Windows wheel
  (`setup_worker_env.py --dry-run` prints the exact filename). `rapidocr` is
  excluded: its onnxruntime backend has no cp314 wheel. No pytest (unittest).
- `python reality_engine/scripts/setup_worker_env.py` installs missing packages
  into the user site with `--timeout 120 --retries 5`; it is idempotent and
  prints what changed. `--dry-run` installs nothing.
- Optional per-task venv: `python -m venv .venv-<task>` (gitignored), then
  `.venv-<task>\Scripts\python -m pip install -r requirements-worker.txt`. Use
  one only when a task needs pins that conflict with the shared site.
- `tasks/worker_context/pip.ini` and `uv.toml` are the same timeouts as a config
  file for interactive use; workers already inherit them through env vars.

## 7. Files Claude must install outside the worker sandbox

The worker cannot write `~/.dsh`, `%APPDATA%`, or the main checkout's `.git`.
Claude (unconfined) installs these after review; exact commands are in the Task
03 report and in `tasks/dsh_profiles/README.md`:

- `tasks/dsh_profiles/headless.cordis.patch.yml` → `~/.dsh/profiles/headless/cordis.patch.yml`
- `tasks/dsh_profiles/web.cordis.patch.yml` → `~/.dsh/profiles/web/cordis.patch.yml`
- `tasks/worker_context/pip.ini` → `%APPDATA%\pip\pip.ini`
- `tasks/worker_context/uv.toml` → `%APPDATA%\uv\uv.toml`

Back up each existing file first. The profile change adds the 10-minute pwsh cap
and turns `promoteOnTimeout` off, so a command that reaches the cap is killed
instead of being promoted to a background job.
