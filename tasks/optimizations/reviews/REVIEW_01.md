# Review task — independent acceptance check of optimisation task 01

You are a reviewer, not the author. Your workspace is the author's finished worktree `C:\Users\warri\Downloads\IDM-worktrees\20261024T192703Z-4b9de800`
(branch `dsh/20261024T192703Z-4b9de800`, base `551226e`). Read `tasks/optimizations/00_SHARED_CONTEXT.md` (sections Machine, Tests,
Known sandbox limits only) and the brief `tasks/optimizations/01_CONTEXT_PACK_AND_BRIEF_TEMPLATE.md`.

## Rules
- Do NOT edit, add or commit any tracked file. Scratch output goes under `./.tmp/review/` only.
- Read-only on live data (`reality_engine/data/`): never write a DB.
- Do not trust the author's report; re-run things yourself. If a check cannot run in your sandbox, say exactly
  why (error text) and mark it BLOCKED, not PASS.

## Do
1. `git diff --stat 551226e..HEAD` and `git log --oneline 551226e..HEAD`. List files touched outside the brief's
   deliverables (scope creep). Ownership: task 01 may edit start_worker brief assembly in plugins/dsh-worker/server/core.py and new files; it must NOT edit supervisor.py sandbox/env code (task 03 owns it) — flag any supervisor.py hunk. The author reported one transient suite failure that did not reproduce: run the test command 3 times and report each result; if any fails, give the failing test name and traceback head. Also check the secret filter in build_worker_context.py does not silently drop legitimate content lines (e.g. lines merely mentioning a column named *_key).
2. Run every numbered item in the brief's "Acceptance checks", in order. For each, record the exact command and the
   decisive lines of output (≤ 10 lines).
3. Run the test command: `python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_dsh_worker_stress` — report pass/fail/error counts.
4. `git grep -nE "sk-[A-Za-z0-9]{20}|api[_-]?key\s*=\s*['\"][^'\"]{12}" 551226e..HEAD -- . ` style check on the diff
   for secrets (`git diff 551226e..HEAD | grep -nE ...`). Report hits or "none".
5. Read the diff once for obvious defects: dead code, hard-coded absolute paths that break other machines/worktrees,
   swallowed exceptions, tests that assert nothing.

## Final answer (exactly this shape, ≤ 60 lines)
VERDICT: PASS | FAIL | PASS-WITH-NOTES
CHECKS:
- AC1: PASS|FAIL|BLOCKED — command — evidence
- ...
TESTS: <command> → N passed / M failed / K errors
SCOPE: ok | out-of-scope files: ...
SECRETS: none | ...
DEFECTS: numbered, each with file:line and a one-line fix
NEEDS-CLAUDE: anything that must be installed/run outside the sandbox before the feature works
