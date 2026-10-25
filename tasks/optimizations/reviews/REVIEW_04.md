# Review task — independent acceptance check of optimisation task 04

You are a reviewer, not the author. Your workspace is the author's finished worktree `C:\Users\warri\Downloads\IDM-worktrees\20261024T192715Z-b16ead85`
(branch `dsh/20261024T192715Z-b16ead85`, base `551226e`). Read `tasks/optimizations/00_SHARED_CONTEXT.md` (sections Machine, Tests,
Known sandbox limits only) and the brief `tasks/optimizations/04_LSP_CODE_INTELLIGENCE.md`.

## Rules
- Do NOT edit, add or commit any tracked file. Scratch output goes under `./.tmp/review/` only.
- Read-only on live data (`reality_engine/data/`): never write a DB.
- Do not trust the author's report; re-run things yourself. If a check cannot run in your sandbox, say exactly
  why (error text) and mark it BLOCKED, not PASS.

## Do
1. `git diff --stat 551226e..HEAD` and `git log --oneline 551226e..HEAD`. List files touched outside the brief's
   deliverables (scope creep). Expected: new files under plugins/code-intel/, reality_engine/tests/test_code_intel.py, pyrightconfig.json, tasks/dsh_profiles/code-intel.insert.yml, tasks/optimizations/install/*. PROGRESS_NOTES.md at repo root is known junk (will be dropped at merge) - do not count it. Specific questions: (a) AC2 handshake <2 s: the author claims the floor is 'import mcp.server' (1.9-4 s). Measure 5x each: bare 'python -c "import mcp.server"' and the real initialize round-trip; report medians and whether the server does ANY avoidable work before replying (imports of heavy modules at top level, LSP spawn, file scans). (b) Say whether the language server was actually available when you ran the tests (how many tests ran vs skipped) - a skipped suite is not a pass for AC1/AC3. If basedpyright is not importable, try 'pip install --target .tmp/bp basedpyright' and run with PYTHONPATH/CODE_INTEL_LANG_SERVER pointing there. (c) Kill the server process mid-request and confirm no node child survives (author claims a leak was fixed).
2. Run every numbered item in the brief's "Acceptance checks", in order. For each, record the exact command and the
   decisive lines of output (≤ 10 lines).
3. Run the test command: `python -m unittest reality_engine.tests.test_code_intel` — report pass/fail/error counts.
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
