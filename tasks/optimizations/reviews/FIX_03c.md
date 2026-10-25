# Fix task 03 — round 3: security re-review findings

Workspace: `C:\Users\warri\Downloads\IDM-worktrees\20261024T192711Z-cecb3619` (branch `dsh/20261024T192711Z-cecb3619`,
HEAD `4ac509b`). The security re-review FAILED. Its findings are in
`C:\Users\warri\Downloads\Info_Diffusion_Model\plugins\dsh-worker\runtime\jobs\20261024T220404Z-1e48a1bd\result.md`
(read it first if you can; the essentials are repeated below). Its attack scripts are in `.tmp/rereview/` of this
worktree — **they are your regression suite**: `poc_snapshot_escape.py`, `snapshot_exec.py`, `snapshot_attack.py`,
`commit_attacks.py`, `ctxpack_attack.py`, `exp_config.py`, `request_fields.py`, plus `.tmp/review/request_channel_poc.py`.
Earlier decisions in `tasks/optimizations/reviews/FIX_03.md` still stand.

## Fix (manager decisions — follow these)

1. **CRITICAL (NEW-1)** — every git command the supervisor or manager runs against a worker's workspace (post-run
   snapshot `gitutil.py:~535-570` via `supervisor.py:~646`, the baseline snapshot at `core.py:~1229`, `changed_since`,
   auto-commit, any status/branch read) must use the stored identity from job start through the hardened runner
   (`_trusted_git`), never `git -C <workspace>`. A tampered `.git` pointer → no git command runs; the snapshot is
   reported as `unavailable: git_dir_tampered` (do not fall back to plain git). Note this path existed on main
   before task 03 — the fix must cover jobs that have no stored identity (legacy job records): treat as no snapshot.
2. **HIGH (NEW-3)** — the hardened runner must make every git invocation inert against config/attribute code paths:
   in-tree and info `.gitattributes` ignored (e.g. `GIT_ATTR_SOURCE`/`--attr-source` pointing at the empty tree, if the
   installed git supports it — check `git --version`; otherwise refuse when any attributes file names a `filter=`/
   `diff=`/`merge=` driver), `core.attributesFile=NUL`, `commit.gpgSign=false`, `gpg.program=`, `core.editor=`,
   `sequence.editor=`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=NUL`, `GIT_TERMINAL_PROMPT=0`, no pager, plus the
   existing hooksPath/fsmonitor/sshCommand/diff.external neutralisation. Keep a single list with a comment per entry.
3. **MEDIUM (NEW-5)** — before `git add -A`, refuse the commit (`reparse_point_in_workspace`) if any untracked or
   modified path in the workspace is a symlink or junction (Windows reparse point) — check with
   `os.lstat`/`st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT`, bounded to the `git status --porcelain -z` list.
4. **HIGH (NEW-2, NEW-4, NEW-6, attacks a/b via repo-root)** — policy: a **mutating** `start_worker` whose workspace is
   the main checkout root (not a worktree) can rewrite code that later runs unsandboxed (the context-pack builder,
   `supervisor.py`, `.git/config`, other jobs' records). Require an explicit `confirm_repo_root_write=true` for that
   case (refuse with `repo_root_write_requires_confirmation` otherwise), record it in job.json/status like
   `approved_by`, expose it in plugin_server, document the trust implication in SANDBOX.md and README in plain words.
   Read-only workers and worktree workers are unaffected. Additionally, `attach_context_pack` must not regenerate the
   pack while any mutating repo-root job is running (skip with a warning).

## Acceptance
1. Every attack script listed above, re-run, reports the attack BLOCKED (update a script only to make it report
   pass/fail clearly — do not weaken what it attempts). Paste each script's final line.
2. `python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_dsh_worker_stress reality_engine.tests.test_dsh_worker_sandbox`
   passes twice, and once more with `PYTHONUTF8=0`. New tests: tampered pointer → snapshot unavailable and no git run
   (assert a fake fsmonitor/hook marker file is NOT created); filter + gpg config inert; junction refused;
   repo-root mutating start refused without the flag, allowed with it.
3. Normal job-created and existing-worktree commits and snapshots still work (existing tests).
4. Leave changes uncommitted; list files; per item: file:line + test.

## Out of scope
Moving the plugin/runtime out of the checkout (Shivam decides; just record it as an open problem with a sketch).
