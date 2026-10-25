# Fix task 01 — context pack review defects (round 1)

Workspace: finished task-01 worktree `C:\Users\warri\Downloads\IDM-worktrees\20261024T192703Z-4b9de800`
(branch `dsh/20261024T192703Z-4b9de800`, commit 8efd88b). Brief: `tasks/optimizations/01_CONTEXT_PACK_AND_BRIEF_TEMPLATE.md`
(note: that brief gave the wrong curated-descriptions path; the real file is `plugins/reality-data/catalog_descriptions.yaml`).
An independent review passed all acceptance checks with these defects. Fix all nine; nothing else.

DEFECTS:
1. `reality_engine/scripts/build_worker_context.py:36` — `DESCRIPTIONS_RELATIVE` points at `plugins/reality-data/server/catalog_descriptions.yaml`; the real file is `plugins/reality-data/catalog_descriptions.yaml`, so 0 of 224 curated descriptions/key-column sets load (patched path changes 67 data-map rows) — fix the path.
2. `reality_engine/scripts/build_worker_context.py:616-619,704-710` — `_secret_marker` drops any line containing substring `sk-`; the legitimate decision line containing "task-notification" is lost (the "1 line(s) omitted" marker) — match `\bsk-[A-Za-z0-9_-]{8,}` and update the test's `assertNotIn("sk-")`.
3. `reality_engine/tests/test_dsh_worker_stress.py:827` — `assertNotIn("?", brief)` now scans the whole delivered brief (header + pack path + task text); a legitimate brief with a question mark fails — assert on the `PROGRESS_NOTES_INSTRUCTION` suffix only.
4. `reality_engine/scripts/build_worker_context.py:180-181` — repo-map `.py` counts use `rglob` without `SKIP_DIRS`, so ignored `plugins/dsh-worker/runtime/` test fixtures change output — prune SKIP_DIRS when counting.
5. `tasks/worker_context/CONTEXT.md:3` — committed pack records `git HEAD: 551226e` (HEAD is 8efd88b) and this machine's absolute data root; `ensure_pack` only checks mtime, so a fresh checkout treats it as current — regenerate at HEAD and treat a header HEAD/data-root mismatch as stale.
6. `reality_engine/scripts/build_worker_context.py:742` — prints `{tokens_estimate}k` where the value is already tokens ("20144k tokens est") — drop the `k`.
7. `reality_engine/scripts/build_worker_context.py:497` — query snippet uses `os.environ` with no `import os` — add the import.
8. `reality_engine/scripts/build_worker_context.py:310-313` — `MAX(rowid)` fails on WITHOUT ROWID tables, leaving 11 schema tables (e.g. `shareholding`) at `rows: ?` — fall back to a bounded `COUNT(*)` for the small tables.
9. `plugins/dsh-worker/README.md:278` — success_check docs still list only `{db, sql, expect}` while `worker_context` uses `kind: file` — document the file form.

Also fix the same wrong path wherever it appears in text you own (template, SKILL.md, README).
Do NOT edit `supervisor.py`. Do NOT regenerate the committed `tasks/worker_context/CONTEXT.md` (Claude regenerates it
at merged HEAD); do make the staleness check also treat a header git-HEAD/data-root mismatch as stale.

## Acceptance
- `python -m unittest reality_engine.tests.test_dsh_worker_plugin reality_engine.tests.test_dsh_worker_stress` → all pass (81 + new).
- `python -m reality_engine.scripts.build_worker_context --data-root C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data --out-dir .tmp/fix01`
  → curated descriptions loaded (report how many tables carry a curated line), the "task-notification" decision line present,
  no `k tokens` typo, <= 25k tokens.
- One test per behaviour change (defects 1, 2, 3, 4, 5).
- Leave changes uncommitted (the sandbox cannot commit in this worktree yet); list the changed files.

Final answer: per defect, file:line changed + covering test; test counts; the builder numbers above.
