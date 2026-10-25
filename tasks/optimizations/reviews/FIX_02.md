# Fix task 02 — toolbelt review defects (round 1)

Workspace: the finished task-02 worktree `C:\Users\warri\Downloads\IDM-worktrees\20261024T192707Z-46114a74`
(branch `dsh/20261024T192707Z-46114a74`, one commit `7bb2ad0` on base `551226e`). Brief: `tasks/optimizations/02_TOOLBELT.md`.
An independent review failed acceptance check 3 and found the defects below. Fix exactly these; no other changes.

1. `reality_engine/toolbelt/drive_fetch.py:216` — `--dry-run` must not require `--dest` inside a sandbox (AC3 command
   `drive_fetch --dry-run <path>` must work). `if dest is None and _in_sandbox() and not dry_run:`.
2. `reality_engine/toolbelt/find_docs.py:58-65,261` — `chunk_count` reads `document_chunks` (FK `raw_documents.doc_id`)
   for ids from every store, so it reports chunks of unrelated docs (live DEEDEV corporate id 24825 → 2 chunks of a
   2021 PIB raw doc; real `cc_items` = 80). Count per store in its own id space: `raw_documents`→`document_chunks`,
   `cc_docs`→`cc_items`, `ar_docs`→`ar_pieces`, `deck_sources`→`pages` (check real FK column names with
   `PRAGMA table_info`). Where a store has no piece table, return `null`, not 0. Fix the tests at
   `test_toolbelt.py:103-116,173-174` that assert the wrong id space.
3. `reality_engine/toolbelt/render_pages.py:44-47,69` — reuse production `extract_deck_figures.text_numbers` (+ its
   `keep` filter) instead of the private `_text_numbers`, so `deck_route` matches the deck gate.
4. `reality_engine/toolbelt/render_pages.py:33,129` — default rendering must reproduce the deck renderer: long side
   capped at `MAX_SIDE=1600` (per-page zoom). Keep `--dpi` as an explicit override.
5. `reality_engine/toolbelt/find_docs.py:64` — narrow `except Exception` to `sqlite3.OperationalError` (missing table);
   let timeouts surface.
6. `reality_engine/toolbelt/mod_test.py:195-198` — `ok` must be false when every check was skipped (missing
   `claude`/`npx`); report `skipped` explicitly.

## Acceptance
- `python -m unittest reality_engine.tests.test_toolbelt` passes, with a new/changed test for each of 1, 2, 4, 6.
- Live, read-only: `python -m reality_engine.toolbelt.drive_fetch --dry-run "<a pdfs/<SYM>/ANNUAL_REPORT/... path from ar_docs>"`
  → present; `find_docs --symbol DEEDEV --doc-type CONCALL_TRANSCRIPT` shows cc chunk counts from `cc_items` (≈80 for id 24825's cc doc).
- Then commit in the worktree: `git add -A reality_engine .gitignore && git commit -m "fix(toolbelt): review round 1 defects"`.
  If git commit is blocked by the sandbox, say so and leave the changes staged.

Final answer: per defect, the file:line changed and the test that covers it; test counts; commit hash or the blocking error.
