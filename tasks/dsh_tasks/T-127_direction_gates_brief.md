# T-127 round 1: Shivam's directions enforced by code

Ticket: T-127

Goal: three code gates and one intake command, so rules that today rely on Claude remembering them are refused
by code. Measured 8 Nov: 9 of 25 rulings in `tasks/RULINGS.md` are code-enforced
(`D:\RealityEngine\reports\standing_rules.xlsx`, built by `reality_engine/scripts/standing_rules_report.py`).

Evidence (Opus, 8 Nov 2026):
- Worker reviews live in `tasks/efficiency/worker_reviews.jsonl`, one JSON object per line, key `id` = the dsh job
  id (e.g. `20261108T114201Z-41e0aa80`) or `agy-<job id>`. Merges of `dsh/<job_id>` branches have happened with
  no review row (standing order in RULINGS "Log every worker and session ...").
- `reality_engine/scripts/doc_gate.py`: `check(staged, *, branch, merging, read, root)` (line ~77) is the
  pre-commit gate; `main()` (line ~190) computes `merging` from `.git/MERGE_HEAD`. Opus merges by hand with
  `git merge --no-ff --no-commit dsh/<job_id>` and a custom message, so the branch name is NOT in MERGE_MSG: get it
  with `git for-each-ref --format=%(refname:short) --points-at <MERGE_HEAD sha> refs/heads/dsh`.
- `plugins/dsh-worker/server/core.py` `start_worker` (line ~1071): the peak gate is at ~1131 (`is_peak`,
  `self._log_refusal("start_gate_peak", ...)`, `raise PluginError(...)`); the brief gate at ~1151. Running jobs:
  `list_workers` (~3344) / `get_status(job_id)["running"]`. RULINGS: "Max 2 code workers at once".
- Ruling count / enforcement map: `standing_rules_report.CODE_GATES` (tag -> description) and `CODE_EXTRA`
  (regex -> description). `project_context.sections(text)` parses RULINGS bullets.
- RULINGS.md caps: 8,000 characters and 40 lines (`doc_gate.CHAR_LIMITS` / `LINE_LIMITS`). Tickets are written
  ONLY through `reality_engine/scripts/task_board.py` `add(...)` (the tracker file is deny-listed for edits).

Steps:
1. Gate A, review before merge (`doc_gate.py`): when `merging` and the MERGE_HEAD commit is the head of a
   `refs/heads/dsh/<job_id>` branch, refuse unless `tasks/efficiency/worker_reviews.jsonl` (staged version, read via
   the existing `read` callable, else the working file) has a row whose `id` equals `<job_id>`. Message:
   `merge of dsh/<job_id> without a worker review row in tasks/efficiency/worker_reviews.jsonl`. Add a `gate_rule`
   name `worker_review`. Keep `check()`'s signature backward compatible (new keyword `merge_branch: str | None = None`).
2. Gate B, tests with code (`doc_gate.py`): on a merge into main, when staged `.py` files outside `tests/` and
   `reality_engine/tests/` and `plugins/*/tests/` change, refuse unless at least one staged test file changes OR the
   staged diff adds no new `def ` at top level (pure fix). Message names the code files. Gate rule `merge_tests`.
3. Gate C, two code workers (`core.py` `start_worker`): before the brief gate, count jobs that are running, on host
   msi, with a worktree or a mutating permission (not `read-only`); if >= 2, `self._log_refusal("start_gate_limit",
   "code_worker_limit")` and raise `PluginError("code_worker_limit", "two code workers are running ...",
   running=[job ids])`. `read-only` permission and `host='hp'` starts are not counted and not refused.
4. Intake command `reality_engine/scripts/ruling.py`:
   `python -m reality_engine.scripts.ruling add --section "<RULINGS section>" --text "<rule>" [--check "<gate tag>"] [--ticket-title "<gate to build>"]`
   - appends `- <text> [check: <tag>]` as the last bullet of that `## ` section of `tasks/RULINGS.md`; refuses (exit 1,
     no write) if the file would exceed 8,000 characters or 40 lines, printing by how much;
   - when no `--check` is given, opens a ticket through `task_board.add(section="Workspace", title=f"Gate for ruling: {text[:120]}" or --ticket-title, accept="standing_rules.xlsx shows a code gate for it", source="ruling intake")` and prints its id;
   - regenerates the standing-rules sheet (`standing_rules_report.write()`, wrapped so a locked xlsx prints a warning);
   - `ruling list` prints sections and bullet count, characters and lines left.
   Register gate tags `worker_review`, `merge_tests`, `code_worker_limit` in `standing_rules_report.CODE_GATES`.
5. Tests: extend `reality_engine/tests/test_doc_gate.py` (A: refused without row, passes with row, non-dsh merge
   unaffected; B: code without tests refused, with a test file passes, non-merge commit unaffected); extend
   `reality_engine/tests/test_dsh_worker_plugin.py` for C using the existing fake-job fixtures (third start refused,
   read-only start allowed); new `reality_engine/tests/test_ruling.py` (append into a temp RULINGS copy, cap refusal,
   ticket opened in a temp tracker root: `task_board` functions take `root=`). Never write the real RULINGS.md,
   TASKS.md or reports folder in tests (`REALITY_REPORTS_DIR`, `REALITY_TICKET_BOARD_SYNC=0`, temp roots).
6. Docs: `docs/DEVELOPER_GUIDE.md` paragraph beside the doc_gate / standing-rules text; `plugins/dsh-worker/README.md`
   for gate C.

Files: reality_engine/scripts/doc_gate.py, plugins/dsh-worker/server/core.py, reality_engine/scripts/ruling.py (new),
reality_engine/scripts/standing_rules_report.py (CODE_GATES only), reality_engine/tests/test_doc_gate.py,
reality_engine/tests/test_dsh_worker_plugin.py, reality_engine/tests/test_ruling.py (new), docs/DEVELOPER_GUIDE.md,
plugins/dsh-worker/README.md. Do NOT edit tasks/RULINGS.md, tasks/STATE.md, tasks/TASKS.md.

Accept / Test command(s): `python -m pytest -q reality_engine/tests/test_doc_gate.py reality_engine/tests/test_ruling.py`
and `python -m pytest -q reality_engine/tests/test_dsh_worker_plugin.py` (run each file in its own process) pass;
typecheck the changed .py files.

Pitfalls: `doc_gate.py` runs as a git hook with a bare `python`: no third-party imports, never raise on an
unreadable jsonl (refuse with a message instead); Windows paths; the dsh-worker server must start fast (no new work
at import); keep every existing refusal code unchanged.

Stop if: gate C needs a change to the supervisor or job record format; or any existing test in the three files fails
before your change (report it).

Budget: about 70 tool calls, 2 hours. Use `outline` on core.py instead of reading it whole (4,000+ lines).
