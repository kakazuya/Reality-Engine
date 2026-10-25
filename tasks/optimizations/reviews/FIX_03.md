# Fix task 03 — sandbox review: security defects (round 1)

Workspace: finished task-03 worktree `C:\Users\warri\Downloads\IDM-worktrees\20261024T192711Z-cecb3619`
(branch `dsh/20261024T192711Z-cecb3619`). Brief: `tasks/optimizations/03_SANDBOX_AND_FREEDOM.md`.
An independent security review FAILED this branch. Its proof-of-concept is `.tmp/review/request_channel_poc.py` in this
worktree — read it first and keep it working as a regression. Fix all eight defects below; nothing else.

DEFECTS:
1. CRITICAL `plugins/dsh-worker/server/supervisor.py:319-335,351,655` — the commit path trusts the workspace `.git` file; a default `workspace` job can rewrite `.git` to a worker-owned fake gitdir inside its workspace, and `_handle_commit_request` runs `git add -A`/`git commit` with the worker's hooks. Proven: fake `pre-commit` wrote `handler-hook-escaped.txt` and the handler returned `ok:true`; redirecting `.git` at a scratch main repo committed `poc redirected commit` onto its `master` and moved its HEAD. Fix: capture the real gitdir at job start (outside the worker), run git with `--git-dir=<stored> --work-tree=<workspace>`, require common dir `== <repo>/.git`, and add `--no-verify`/`core.hooksPath=`.
2. HIGH `core.py:1061-1074` + `supervisor.py:753` — data/full always force `danger-full-access`; `writes=[]` is accepted although `README.md:133`/`SKILL.md:49` say DB names are required, so a data job can write any DB holding no lock; `confirm_*` is self-asserted by the same caller. Fix: refuse data scope with empty `writes` and require an explicit full-access request/approval token.
3. MEDIUM `worker_bootstrap/sitecustomize.py:24-35` — global `os.mkdir` patch with no `os.name`/sandbox guard; on POSIX (or a full-access job) it changes `0o700` to `0o777` for every Python process, and `test_dsh_worker_sandbox.py:374-400` passes without the patch. Fix: apply only on `win32` with a sandbox marker; assert the inherited DACL in that test.
4. LOW `core.py:1143` vs `supervisor.py:753` — manager pre-check takes and releases the lock; supervisor acquires it later, so two simultaneous data starts both pass and the loser fails after launch (`resource_busy`); the test avoids the race by waiting for `running`. Fix: hold/reserve the lock in the manager until the supervisor starts.
5. LOW `tasks/worker_context/orientation_baseline.json` — 4 in-flight jobs have stale `total_tool_calls` (e.g. `20261024T192711Z-cecb3619`: 103 vs live 221); first-edit counts match. Fix: regenerate after those jobs finish.
6. LOW `core.py:1803` — `get_status` prefers `job.json`'s `write_scope` over `status.json`; a worker whose workspace is the main checkout can spoof scope in `worker_status` (our PoC: status said `data`, launch still refused). Fix: prefer `status.json`.
7. LOW `tasks/worker_context/sandbox_probe.py:9-15` — hard-coded `C:\Users\warri\...` paths. Fix: derive from repo root/`%CD%`.
8. LOW `supervisor.py:366-368,519-527` — `worker_commits`/`detached` grow unbounded. Fix: cap to the last N entries.

## Manager decisions (follow these)
- D1: the supervisor must never derive a git dir from anything the worker can write. Record the real `git_dir`,
  `common_dir` and `toplevel` in the job record **at job start** (computed by the manager before launch), and at
  commit time run `git --git-dir=<stored git_dir> --work-tree=<workspace> -c core.hooksPath=NUL -c core.fsmonitor=false
  commit --no-verify ...` (and the same for `add`). Refuse if the stored common dir is not `<repo>/.git`, or if the
  stored git_dir is the main checkout's own `.git` (never commit the main checkout). Also ignore any repo-local config
  that could execute code (`-c core.sshCommand=`, `-c diff.external=`, no `-c` from the request file). Only ever commit
  to the job's own branch; refuse if HEAD of the stored git_dir is not `refs/heads/dsh/...` or the recorded branch.
- D1 regression tests: (a) worker rewrites `.git` to a fake gitdir with a pre-commit hook → hook does NOT run, commit
  refused or lands only in the real worktree; (b) `.git` redirected to another repo → refused, that repo's HEAD unchanged;
  (c) normal worktree commit still works for both job-created and existing worktrees.
- D2: `write_scope="data"` with empty `writes` → refused (`writes_required`). Keep `confirm_full_access` as the caller flag
  (the caller is Claude; Shivam's per-use approval is a process rule) but record `approved_by` text in job.json and status.
  Document in SANDBOX.md plainly that dsh 0.2.1 makes data == full access at the OS level.
- D3: apply the mkdir patch only when `sys.platform == "win32"` and the env marker the supervisor sets for sandboxed
  (workspace-scope) jobs is present; add the inherited-DACL assertion to the test.
- D6: status.json wins over job.json for scope.
- D4, D5 (regenerate baseline now that the 4 jobs are finished), D7, D8: as the reviewer wrote.

## Acceptance
- `python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_dsh_worker_stress reality_engine.tests.test_dsh_worker_sandbox` → all pass, run twice.
- `python .tmp/review/request_channel_poc.py` (update it if needed) shows: hook did not run, redirect refused, normal commit ok.
- Leave changes uncommitted (this sandbox cannot commit here); list changed files and, per defect, file:line + covering test.
