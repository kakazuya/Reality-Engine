# Security re-review — task 03 after fix round 1 (integrated with main)

You are a security reviewer, not the author. Workspace: `C:\Users\warri\Downloads\IDM-worktrees\20261024T192711Z-cecb3619`
(branch `dsh/20261024T192711Z-cecb3619`). History: original work `eacb8bd`; the round-1 security fix `158e04e`; then a merge
of `main` (task 01 context pack + 02 toolbelt + 04 code-intel) whose 3 conflicts (core.py, plugin_server.py, README.md)
were resolved by Claude as "keep both sides". The previous review is `tasks/optimizations/reviews/REVIEW_03.md` (brief)
and its findings are listed in `tasks/optimizations/reviews/FIX_03.md` (defects + manager decisions). Its proof of concept
is `.tmp/review/request_channel_poc.py` in this worktree.

## Rules
Do not edit or commit tracked files; scratch under `./.tmp/rereview/` only. Never write live DBs. Never touch the main
checkout `C:\Users\warri\Downloads\Info_Diffusion_Model` or any repo other than scratch repos you create under `.tmp/rereview/`.

## Do
1. Re-run the PoC: `python .tmp/review/request_channel_poc.py`. Report each step.
2. For each of the 8 defects in FIX_03.md: is it fixed as the manager decision requires? cite file:line.
3. Attack the commit path again with NEW variants, each in a scratch repo + scratch worktree you create:
   a) `.git` file kept but the worktree's real gitdir `config` edited by the worker? (is `<common>/worktrees/<id>/` writable
      from the workspace sandbox? if the supervisor reads any config from there, can it run code?) — `core.hooksPath`,
      `core.fsmonitor`, `filter.<x>.clean/smudge` + `.gitattributes` in the workspace (clean filters run on `git add`!),
      `diff.external`, `core.sshCommand`, `gpg.program` + `commit.gpgsign=true`, `core.editor`, `includeIf`/`include.path`.
   b) workspace `.gitattributes` with `* filter=evil` + repo-level or global config defining `filter.evil.clean` — does
      `_trusted_git` neutralise filters (e.g. `-c filter.<name>.clean=` is per-name; is there `--no-filters`?)
   c) symlink / junction inside the workspace pointing outside it, then a commit request — does `git add -A` follow it?
   d) request-file fields: can anything in `.tmp/commit.request.json` reach a git argument, a path, or an env var?
   e) `launch.request.json` from a `workspace`-scope job → refused? cite the check.
4. Conflict resolution review: in `plugins/dsh-worker/server/core.py` start_worker, confirm the git identity is captured
   **before** the brief/context-pack step and that `attach_context_pack` (runs unsandboxed in the manager) cannot be
   steered by worker-written files to execute code or write outside `tasks/worker_context/`.
5. Run `python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_dsh_worker_stress reality_engine.tests.test_dsh_worker_sandbox` once.

## Final answer (≤ 60 lines)
VERDICT: PASS | FAIL | PASS-WITH-NOTES
POC: per step
DEFECTS-1..8: FIXED | NOT-FIXED — file:line
NEW-ATTACKS: a..e — BLOCKED | ESCAPES (with the exact reproduction) | N/A
CONFLICT-RESOLUTION: ok | problem
TESTS: counts
NEW-DEFECTS: numbered, severity, file:line, one-line fix
