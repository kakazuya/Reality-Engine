# Fix task 03 — round 2: two test failures found by Claude outside the sandbox

Workspace: `C:\Users\warri\Downloads\IDM-worktrees\20261024T192711Z-cecb3619` (branch `dsh/20261024T192711Z-cecb3619`,
HEAD `07ea26d` = your round-1 fix `158e04e` + a merge of main, conflicts already resolved). Read `tasks/optimizations/reviews/FIX_03.md`
for the round-1 decisions; they still stand.

Claude ran `python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_dsh_worker_stress reality_engine.tests.test_dsh_worker_sandbox`
**unsandboxed** → 106 tests, 2 failures. Failure 1 also reproduces on `158e04e` alone (so it is the round-1 fix, not the merge).

## Failure 1 — REAL BUG: auto-commit of a legitimate worktree refused
`test_dsh_worker_stress.SharedControlProcessTests.test_two_server_worktree_demo_steering_and_auto_commit` (line ~1019):
`'committed': False, 'commit_reason': 'git_workspace_moved', 'commit_error': 'refused: git_workspace_moved'` for a
job-created worktree at `...\runtime\test-tmp\dsh stress \u0942 <hex>\worktrees\<job_id>` (path has a space and a
non-ASCII char). Find why `identity_error` thinks the workspace moved (likely path representation: case, `\\?\`, 8.3
short names, unicode normalisation, forward vs back slashes, `git rev-parse --show-toplevel` output encoding, or the
`.git` pointer text comparison). Compare with `os.path.normcase(os.path.realpath(...))` on both sides — **without**
weakening the check: a `.git` pointer to a different gitdir, or a toplevel that is a different directory, must still be
refused (the round-1 regression tests must keep passing). Explain in the report why it passed for you in round 1.

## Failure 2 — fragile test
`test_dsh_worker_sandbox.WorkerBootstrapTests.test_bootstrap_only_patches_a_sandboxed_windows_worker` (line ~616):
`assertNotIn("(I)", plain_acl.stdout)` matched `Mandatory Label\Low Mandatory Level:(I)(OI)(CI)(NW)` — an inherited
integrity label on the directory (this worktree has been used by sandboxed runs), not an inherited user ACE. Assert on
inherited **access** ACEs only (ignore `Mandatory Label` lines). It passes in a fresh directory; must pass in both.

## Acceptance
- The full command above passes (106 tests) in this worktree — run it twice.
- `python .tmp/review/request_channel_poc.py` still prints ALL POC EXPECTATIONS HELD.
- Leave changes uncommitted; list changed files; per failure: root cause in one sentence + file:line + test.
