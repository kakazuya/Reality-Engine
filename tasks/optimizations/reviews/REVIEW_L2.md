# Review task — independent acceptance check of optimisation task L2 (document lookups)

You are a reviewer, not the author. Your workspace is the author's finished worktree `C:/Users/warri/Downloads/IDM-worktrees/20261025T074948Z-e3822c50`
(branch `dsh/20261025T074948Z-e3822c50`, base `2260df7`). Read `tasks/optimizations/00_SHARED_CONTEXT.md` (sections Machine, Tests,
Known sandbox limits only) and the brief `tasks/optimizations/lookups/L2_DOC_LOOKUPS.md`.

## Rules
- Do NOT edit, add or commit any tracked file. Scratch output goes under `./.tmp/review/` only.
- Read-only on live data (`reality_engine/data/`): never write a DB.
- Do not trust the author's report; re-run things yourself. If a check cannot run in your sandbox, say exactly
  why (error text) and mark it BLOCKED, not PASS.

## Do
1. `git diff --stat 2260df7..HEAD` and `git log --oneline 2260df7..HEAD`. List files touched outside the brief's
   deliverables (scope creep). `PROGRESS_NOTES.md` at the repo root and an empty `tmp_*` dir are known strays (manager removes them).
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
6. Re-run the brief's live calls yourself and confirm each quote exists in the source (open the chunk / PDF page).
7. Date matching: pick 4 documents and request them at d-1, d, d+1 and d+4. Confirm the right document wins, the
   exact matched date is reported, and d+4 gives found:false with that doc in `nearest`. Include one company with
   two documents of the same type within 3 days.
8. Page numbers: for 3 transcripts check that the reported page matches the "page N of M" footer of the quoted text;
   report how often `page` is null.
9. `doc_find` with terms that do not occur → found:false with checked/nearest/hint, no exception; terms with SQL/FTS
   special characters (`"`, `*`, `-`, `'`, `AND`) → no crash, no injection.
10. Bounds: confirm no query scans `document_chunks` without an indexed key (read the SQL; run EXPLAIN QUERY PLAN on
    the main ones); warm calls ≤ 5 s when the PDF is cached locally.
11. Quarantine: confirm `quarantined_doc_ids()` is applied in all three tools.
