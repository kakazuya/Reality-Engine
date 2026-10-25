# Final security check — task 03, round 3 (independent, write your OWN attacks)

Workspace: `C:\Users\warri\Downloads\IDM-worktrees\20261024T192711Z-cecb3619`, branch HEAD = round-3 fix commit.
Previous findings + decisions: `tasks/optimizations/reviews/FIX_03c.md`. The author re-ran the earlier reviewer's attack
scripts in `.tmp/rereview/` and reports all BLOCKED — but the author also edited those scripts, so do **not** rely on
them. Write fresh, minimal attacks under `.tmp/final/` (scratch repos + scratch worktrees you create there only).

## Rules
No edits to tracked files; never touch the main checkout `C:\Users\warri\Downloads\Info_Diffusion_Model` or any repo
outside `.tmp/final/`; never write live DBs.

## Check (≤ 45 min)
1. NEW-1: in a scratch worktree, point `.git` at a worker-owned gitdir whose config sets `core.fsmonitor` (and
   separately `core.hooksPath` + a hook) to a script that writes a marker file; run `gitutil.snapshot(...)` exactly as
   `supervisor.py` calls it post-run, and the baseline snapshot as `core.py` calls it. Marker must not exist.
2. NEW-3: with a legitimate worktree (pointer intact), put `* filter=evil` in the workspace `.gitattributes` AND
   `filter.evil.clean=<marker script>` in every config git would read that the worker could plausibly write
   (worktree-specific `config.worktree` if `extensions.worktreeConfig` is on, `$GIT_DIR/info/attributes`,
   `$HOME/.gitconfig` via env, `GIT_CONFIG_*` env vars inherited by the supervisor). Run the commit path. Marker must
   not exist. Also `commit.gpgSign=true` + `gpg.program=<marker>`.
3. Read `gitutil.py` around the new "replay captured core.autocrlf/core.eol and user.name/user.email" code: when and
   from where are those values captured, and can a worker influence them (e.g. a newline or `-c` injection in
   `user.name`)? Try `user.name` containing `\n[core]\n\tfsmonitor=<marker>` if it is captured from a writable place.
4. NEW-5: junction to a directory outside the workspace, and a file symlink; commit request → refused, nothing staged.
5. Repo-root policy: `start_worker` mutating with workspace = repo root and no flag → refused
   `repo_root_write_requires_confirmation` (call the manager API in-process with a temp config as the tests do).
6. Run `python -m unittest reality_engine.tests.test_dsh_worker_sandbox` once.

## Final answer (≤ 40 lines)
VERDICT: PASS | FAIL
1..5: BLOCKED | ESCAPES (exact repro) — one line each with file:line of the guard
TESTS: counts
NEW-DEFECTS: severity, file:line, one-line fix (only real ones)
