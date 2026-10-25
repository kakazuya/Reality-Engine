# Review task — independent acceptance check of optimisation task 03

You are a reviewer, not the author. Your workspace is the author's finished worktree `C:\Users\warri\Downloads\IDM-worktrees\20261024T192711Z-cecb3619`
(branch `dsh/20261024T192711Z-cecb3619`, base `551226e`). Read `tasks/optimizations/00_SHARED_CONTEXT.md` (sections Machine, Tests,
Known sandbox limits only) and the brief `tasks/optimizations/03_SANDBOX_AND_FREEDOM.md`.

## Rules
- Do NOT edit, add or commit any tracked file. Scratch output goes under `./.tmp/review/` only.
- Read-only on live data (`reality_engine/data/`): never write a DB.
- Do not trust the author's report; re-run things yourself. If a check cannot run in your sandbox, say exactly
  why (error text) and mark it BLOCKED, not PASS.

## Do
1. `git diff --stat 551226e..HEAD` and `git log --oneline 551226e..HEAD`. List files touched outside the brief's
   deliverables (scope creep). Ownership: 03 owns supervisor.py env/sandbox, permission modes in core.py start params, new files; task 01 owns brief assembly in start_worker - flag any 03 hunk inside brief assembly. SECURITY IS THE PRIORITY of this review: (a) Can a worker started with the default write_scope (workspace) cause ANY command to run outside its sandbox via the new request handlers (launch_detached WMI, worker commit request) - e.g. by writing a request file into its own workspace/.tmp? Read the handler code paths, cite file:line for the scope check, and try it: write the request file a workspace job would write and show whether the supervisor acts on it. (b) Commit request: can it commit/push to any branch other than the worker's own worktree branch, or move HEAD of the main checkout? (c) data/full: confirm the confirm_* flags cannot be bypassed through plugin_server.py params or job.json edits by the worker. (d) worker_bootstrap/sitecustomize.py patches os.mkdir/Path.mkdir for every Python process the worker runs: check it is a no-op outside the sandbox and cannot break normal mode=0o700 semantics in tests. (e) Run the test command TWICE (author hardened two timing tests; report any flake). Read tasks/worker_context/orientation_baseline.json and say whether 'tool_calls_before_first_edit' is computed the same way the new live metric is.
2. Run every numbered item in the brief's "Acceptance checks", in order. For each, record the exact command and the
   decisive lines of output (≤ 10 lines).
3. Run the test command: `python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_dsh_worker_stress reality_engine.tests.test_dsh_worker_sandbox` — report pass/fail/error counts.
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
