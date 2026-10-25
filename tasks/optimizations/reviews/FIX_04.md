# Fix task 04 — code-intel review defects (round 1)

Workspace: finished task-04 worktree `C:\Users\warri\Downloads\IDM-worktrees\20261024T192715Z-b16ead85`
(branch `dsh/20261024T192715Z-b16ead85`). Brief: `tasks/optimizations/04_LSP_CODE_INTELLIGENCE.md`.
basedpyright is not installed in the main Python; the reviewer extracted it to `.tmp/bp` — use
`PYTHONPATH=.tmp/bp` (or `CODE_INTEL_LANG_SERVER`) so the 7 LSP tests run instead of skipping.
An independent review passed every acceptance check with these defects. Fix all three; nothing else.

DEFECTS:
1. `plugins/code-intel/server/core.py:361` — `_name_position` searches the stripped line, so indented symbols land on `def`: `definition("start_worker")` col 5, `references("start_worker")` 0 hits, hover at that position errors. Fix: search the raw line (`_lines(path)[line0]`) — verified col 9, reference + hover work.
2. `plugins/code-intel/server/core.py:339` — cold `workspace/symbol` can answer `[]` before pyright's file index exists: first-call `definition(symbol)` on the fixture returned `not_found` 6/6, and `test_definition_by_symbol` failed 3 consecutive full-suite runs before passing 3/3. Fix: retry `workspace/symbol` once after a short bounded wait when the client was just started (or block on the warm thread's first symbol result).
3. `plugins/code-intel/server/lsp.py:104` — `stop()` never closes `proc.stdout` / `self._stderr_fh` (two `ResourceWarning`s per run, 2 handles leaked per restart). Fix: close both in `stop()` and clear `_stderr_fh` before reopening in `start()`.


Also delete the stray root `PROGRESS_NOTES.md` from the branch (`git rm` is blocked in this sandbox: just delete the file).

## Acceptance
- `python -m unittest reality_engine.tests.test_code_intel` with the language server available: 13 + new pass, **3 consecutive full runs**.
- New tests: indented method `definition`/`references`/`hover` (defect 1); first call right after a cold start finds a symbol (defect 2);
  `stop()` leaves no open handles — run the suite with `-W error::ResourceWarning` (defect 3).
- `python plugins/code-intel/tests/acceptance_check.py` → ALL CHECKS PASSED, plus `references("start_worker")` ≥ 1.
- Leave changes uncommitted (the sandbox cannot commit in this worktree yet); list changed files.
