# Review task — independent acceptance check of optimisation task L1 (market lookups)

You are a reviewer, not the author. Your workspace is the author's finished worktree `C:/Users/warri/Downloads/IDM-worktrees/20261025T074944Z-d9955304`
(branch `dsh/20261025T074944Z-d9955304`, base `2260df7`). Read `tasks/optimizations/00_SHARED_CONTEXT.md` (sections Machine, Tests,
Known sandbox limits only) and the brief `tasks/optimizations/lookups/L1_MARKET_LOOKUPS.md`.

## Rules
- Do NOT edit, add or commit any tracked file. Scratch output goes under `./.tmp/review/` only.
- Read-only on live data (`reality_engine/data/`): never write a DB.
- Do not trust the author's report; re-run things yourself. If a check cannot run in your sandbox, say exactly
  why (error text) and mark it BLOCKED, not PASS.

## Do
1. `git diff --stat 2260df7..HEAD` and `git log --oneline 2260df7..HEAD`. List files touched outside the brief's
   deliverables (scope creep). `PROGRESS_NOTES.md` at the repo root is a known stray (manager removes it). The 1-line change to test_reality_data.py is a declared deviation: judge it.
2. Run every numbered item in the brief's "Acceptance checks", in order. For each, record the exact command and the
   decisive lines of output (≤ 10 lines).
3. Run the test command: `python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"` — report pass/fail/error counts.
4. `git grep -nE "sk-[A-Za-z0-9]{20}|api[_-]?key\s*=\s*['\"][^'\"]{12}" 2260df7..HEAD -- . ` style check on the diff
   for secrets (`git diff 2260df7..HEAD | grep -nE ...`). Report hits or "none".
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

## Extra checks for this task (answers must be right, not just shaped right)
6. Cross-check each live answer against your own direct query (reality-data `sql` tool or `connect_ro`): Ather delivery
   2026-04-13 NSE+BSE; PFC (532810) 2026 YTD high + date on both exchanges; BLACKBUCK promoter % for 2026-09-30;
   LUMAXTECH share count. Confirm 2026-04-14 has no rows market-wide.
7. Try 5 more symbols of your choice (a BSE-only scrip, a recently listed IPO, a stock with an ISIN change, a name
   query, a bad symbol) for each tool: no crash, correct `found:false` + hint where data is missing, ≤ 2 s warm.
8. `holding` share-count selection: try 5 companies with annual reports; report any case where `best_share_count`
   picks a decoy (bucket, promoter-only, shareholder count) or misses the exact figure.
