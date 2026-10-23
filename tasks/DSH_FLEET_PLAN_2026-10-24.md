# dsh fleet: session-independent DeepSeek workers + data-job runner

Status: design by Claude, 2026-10-24 05:30 IST, at Shivam's request ("highest priority"). DeepSeek builds; Claude reviews.

## Goal

Start a platoon of dsh workers that **any** Claude Code session (or several at once) can list, steer, renew, merge and cancel,
independent of which session started them. The same runner also drives the data jobs (PIB, price/volume/delivery fetches,
announcements, XBRL, ...) so they're started, watched and resumed the same way instead of being forgotten.

## Today's blockers (verified in code)

1. Control tokens live only in the starting MCP server's memory (`core.py:254`, `_control_tokens`). Another session (or a restarted
   server) can see a job but can't message it or renew its lease (`control_token_not_in_this_mcp_server`).
2. One mutating worker per repository (`_acquire_lock`), and `workspace` must be inside the repo root. So there's no parallel
   writing, and worktrees under the repo are covered by the same lock.
3. The sandbox can't commit in a worktree: git metadata lives in the main repo's `.git/worktrees/<name>`, outside `workspace-write`.
4. Lease extension is capped at 1800 s.
5. Data jobs are ad-hoc scripts and `.cmd` files with no shared registry, status or "last successful run", so some never ran.

## Design: shared on-disk state, no daemon

Every Claude session already launches its own stdio dsh-worker MCP server, and they all share `plugins/dsh-worker/runtime/`.
The detached supervisors already outlive the server. So session independence needs **shared state on disk**, not a new
long-running service:

### A. Shared control (phase 1)
- Persist each job's control token in its job dir, encrypted with Windows **DPAPI** (CurrentUser scope, via ctypes
  CryptProtectData/CryptUnprotectData; no new dependency), file ACL'd to the user. Any MCP server instance of the same Windows
  user can decrypt it; nothing else can. Never print it.
- `message_worker`, `renew_worker_lease` and `cancel_worker` work from any session. Keep the lease *owner* concept, but add
  `claim_worker(job_id)` (explicit takeover: records the new owner session and the reason) and let `renew` work for the owner, or
  anyone with `adopt=true`.
- **Session identity**: each MCP server gets a `session_label` (env `DSH_SESSION_LABEL`, else hostname+pid+start time). Every
  message, renew, claim and cancel is appended to `job_dir/steering.jsonl` (who, when, kind, first 200 chars), so a session can
  see what other sessions told the worker. `list_workers` shows owner and last steerer.
- **Concurrency**: all job-record writes go through an exclusive file lock (msvcrt.locking) with atomic replace (already
  partly present in store.py); add a test with two server instances racing.
- Lease cap 1800 s -> **7200 s** (Shivam approved 2026-10-24).

### B. Worktree writers (phase 1)
- `start_worker(..., use_worktree=true)`: create `git worktree add <WORKTREES_ROOT>/<job_id> -b dsh/<job_id> <base>` where
  `WORKTREES_ROOT` = sibling of the repo (`C:\Users\warri\Downloads\IDM-worktrees`), base = current HEAD of main unless given.
- Locks become **per workspace path**: one writer per worktree; the main checkout keeps its own lock. The workspace check allows
  repo root OR a registered worktree of this repo (`git worktree list --porcelain`).
- Commits: the worker can't write `.git/worktrees/<name>`, so the **supervisor auto-commits** the worktree when the worker ends
  successfully (`git add -A` within the worktree, author from git config, message = job title + job_id, trailer
  `DSH-Job: <id>`). An empty diff means no commit. Status reports `branch`, `base`, `head`, `commits`, `files_changed`.
- Gitignored data (DBs, indexes) isn't in worktrees: the brief preamble tells workers to read data by absolute path from the
  main checkout, read-only. Expose `REALITY_DATA_ROOT` in the worker env.

### C. Merge queue (phase 2)
- `merge_worker(job_id, target="main", run_tests=true)`: from the main checkout, under a repo-wide **merge lock**, merge
  `dsh/<job_id>` into the target with `--no-ff` (or rebase+ff when clean), run the job's declared test command (or a default
  quick suite), and abort and roll back if the tests fail.
- Conflicts: report the conflicted files and hunks and leave the target clean (`merge --abort`). Optionally use
  **mergiraf** (open-source syntax-aware git merge driver, installed per-repo via .gitattributes) if it's available on PATH;
  otherwise plain git. If a conflict remains, `start_worker` can open a resolver job in a fresh worktree based on the target
  that merges the branch and fixes conflicts (Claude decides).
- **Never push automatically.** `push(target)` is a separate tool that refuses unless the caller passes `confirm=true`, and
  Claude only calls it on Shivam's explicit go-ahead.
- Cleanup: `remove_worktree(job_id)` after merge (keeps the branch unless asked).

### D. Data-job runner (phase 2)
- `plugins/dsh-worker/jobs.yaml` registry: name, command (argv), cwd, env, description, outputs (DB/table it writes), resource
  locks (e.g. `db:equity_intelligence`, `gpu`, `net:nse`), expected cadence (daily/weekly/once), success check (a SQL
  freshness query or log marker), off-peak/market-hours rules, and the max allowed duty.
- Tools: `list_jobs()` (with last success, staleness vs cadence and a "never ran" flag), `start_job(name, args)` (spawned by the
  same supervisor, so status/progress/cancel/leases/session-independence are shared with workers), `job_log(name|run_id, tail)`.
- **Resource locks** are named locks with the same file-lock mechanics, so two jobs never write the same SQLite DB at once and the GPU
  is never double-booked (UPS power-cut history).
- Populate jobs.yaml from the existing scripts (reality_engine/scripts/fetch_*, pib_*, run_*_backfill, *.cmd) and the Windows
  scheduled tasks. The phase-0 audit says which never ran.

## Phases and acceptance

- **Phase 0 (read-only audit, now)**: inventory every data job (script, scheduled task, .cmd); last run (logs, DB max dates,
  scheduled-task history); what it writes; whether it's stale or never ran. Output: tasks/DATA_JOBS_AUDIT_2026-10-24.md.
- **Phase 1**: A + B. Acceptance: session X starts a worktree worker; session Y (a second MCP server process) lists it, messages
  it, renews it to 2 h, claims it; the worker writes a file; the supervisor auto-commits on branch dsh/<id>; two worktree writers
  run at once; all existing dsh-worker tests plus new ones pass.
- **Phase 2**: C + D. Acceptance: two worker branches merged through the queue, one deliberately conflicting (it's reported and the target
  is left clean); jobs.yaml covers the audited jobs; one cheap data job runs through `start_job` with status and log visible from
  another session; resource lock contention is tested.
- After each phase: Shivam restarts the Claude app (or reconnects MCP) to load the new server code.
