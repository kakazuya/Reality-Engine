# Brief template — five labelled lines

Every `start_worker` brief (inline `brief` or `task_file`) must carry these five labelled lines or
sections. A start missing any of them is refused with `brief_incomplete`, naming the missing ones.
Copy this file and fill each line; delete the guidance in italics.

Goal: *one outcome, 1–3 lines: what is true when this is done.*

Files: *exact paths to change, and which are new. Add a "Do not touch" list for files another task owns.*

Accept: *numbered, testable accept checks, each naming the command or the observable result. This is the definition of done. (`Test command(s):` may replace this label.)*

Stop if: *the conditions that must stop the work and report instead, e.g. a change needs files outside the named list or breaks the running-job safety rule.*

Budget: *tool calls before the first edit, total tool calls, paid $, wall time. "No paid calls" when true.*

## Small fixes

`small_fix=true` allows a one-line brief as long as it carries an accept command:

`Fix the typo in tasks/STATE.md. Accept: python -m pytest reality_engine/tests/test_dsh_worker_plugin.py -q`

## Report format

1. What changed (files, one line each).
2. How it was verified (commands + exact pass counts).
3. Anything the controller must install/run outside the worker sandbox.
4. Open problems.
5. Tool calls before first edit / total.
6. Docs updated: every doc changed for this work, and each stale copy fixed or removed. A branch without this is not merged.

## Out of scope

*What the worker must not do, even if it looks related. Naming it prevents scope creep.*
