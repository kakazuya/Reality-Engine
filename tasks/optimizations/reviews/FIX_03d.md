# Fix task 03 — round 4 (two small items, then done)

Workspace: `C:\Users\warri\Downloads\IDM-worktrees\20261024T192711Z-cecb3619`, HEAD `f7b06e5`. The final independent
security review PASSED with one LOW finding; Claude found one failure outside the sandbox. Fix exactly these two.

## 1. Context-pack guard fails outside the sandbox (security guard; must fix)
`python -m unittest reality_engine.tests.test_dsh_worker_sandbox.WriteScopeValidationTests.test_context_pack_is_not_regenerated_while_a_repo_root_writer_runs`
fails **deterministically** when run unsandboxed (Claude's shell, which is also how the real dsh-worker MCP server
runs): `AssertionError: True is not false : the manager executed the builder`. It passes inside your sandbox. The guard is
`core.py` `_repo_root_writer_active()` → `_lock_active(existing)`. Find why the lock record the test writes is judged
inactive outside the sandbox (PID/creation-time verification, process visibility, path case of the lock file, env
differences such as `PYTHONUTF8`, `DSH_WORKER_SANDBOXED`, temp dirs…). You cannot run unsandboxed yourself, so reason from
the code and reproduce the difference (e.g. run the test with the env vars your sandbox sets removed/changed, and with a
lock owner PID that belongs to a process you cannot query). Fix the guard so it fails **closed** when liveness cannot be
verified, without making normal starts fail when no repo-root writer exists. Explain the root cause in one sentence.

## 2. LOW — `.tmp` junction (from the final review)
`supervisor.py:~237-238` `_tmp_dir` and `:~295-298`: if `<workspace>/.tmp` is a reparse point (junction/symlink), refuse to
read or answer requests (return None / record `tmp_reparse_point` in status), reusing `gitutil.reparse_point_path` /
`_is_reparse_point`. Add a test with a junction (`mklink /J` via `cmd /c`, skip only if junction creation is impossible).

## Acceptance
- The full `python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_dsh_worker_stress reality_engine.tests.test_dsh_worker_sandbox`
  passes twice in your sandbox and once with `PYTHONUTF8=0` and `DSH_WORKER_SANDBOXED` unset.
- Leave changes uncommitted; list files; root cause for item 1; file:line + test for both.
