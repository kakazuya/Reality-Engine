# Brief template — one shape for every worker task

Every `start_worker` brief (inline `brief` or `task_file`) follows these sections. `start_worker` lints for
**Goal**, **Acceptance checks** and **Test command(s)** and returns `brief_lint:` warnings when one is missing —
a warning, never a refusal. Copy this file, keep the headings, delete the guidance in italics.

## Goal
*1–3 lines. What is true when this is done. One outcome, not a feature tour.*

## Why
*The problem this fixes, who hits it, and what happens if it is not fixed. Keep it to a few lines.*

## Files to touch
*Exact paths. Say which are new. Add a "Do not touch" list for files another task owns or that must stay stable.*

- `path/to/file.py` — what changes
- `path/to/new_file.py` — new
- Do not touch: `plugins/dsh-worker/server/supervisor.py` (Task 03 owns it)

## Inputs/data
*Exact tables, files, commands, docs. Name the DB and table, not "the database". Mark read-only inputs.*

## Steps
*Ordered, checkable steps. A step that cannot be verified is not a step.*

## Acceptance checks
*Numbered and testable. Each one names the command or the observable result. This is the definition of done.*

1. `<command>` exits 0 and prints `<expected>`.
2. Running the change twice produces the same output.
3. No writes outside `<allowed path>`.

## Test command(s)
*Exact copy-paste commands, including the narrowest first.*

```bash
python -m unittest reality_engine.tests.test_example
python -m unittest discover -s reality_engine/tests -p "test_*.py"
```

## Budget
*Tool calls before first edit, total tool calls, paid $, wall time. "No paid calls" when true.*

- ≤ 25 tool calls before the first edit; ≤ 120 total; ≤ 60 min wall; $0 paid.

## Report format
1. What changed (files, one line each).
2. How it was verified (commands + exact pass counts).
3. Anything the controller must install/run outside the worker sandbox.
4. Open problems.
5. Tool calls before first edit / total.

## Out of scope
*What the worker must not do, even if it looks related. Naming it prevents scope creep.*
