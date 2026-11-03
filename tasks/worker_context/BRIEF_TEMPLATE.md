# Brief template — six labelled lines

Every `start_worker` brief (inline `brief` or `task_file`) must carry these six labelled lines or
sections. A start missing any of them is refused with `brief_incomplete`, naming the missing ones.
Copy this file and fill each line; delete the guidance in italics.

Goal: *one outcome, 1–3 lines: what is true when this is done.*

Files: *exact paths to change, and which are new. Add a "Do not touch" list for files another task owns.*

Accept: *numbered, testable accept checks, each naming the command or the observable result. This is the definition of done. (`Test command(s):` may replace this label.)*

Stop if: *the conditions that must stop the work and report instead, e.g. a change needs files outside the named list or breaks the running-job safety rule.*

Budget: *tool calls before the first edit, total tool calls, paid $, wall time. "No paid calls" when true.*

Ticket: *the row this work closes: `Ticket: T-014`, or `No-ticket: <reason>` when no open row fits.
An unknown T-number is refused with `ticket_unknown`; add the row first with
`python -m reality_engine.scripts.task_board add`. The worker's brief then carries that one row.*

Evidence (required in this project, Shivam 4 Nov 2026; the controller gathers it BEFORE the start): *for each
defect, the rows that show it (table, row ids, values, doc_key + page), the file + function + line to edit, the
columns of every table it will query, and the fast check command (`build --part <part>` on one company, the fixed
check pages). Workers spent ~50 calls rediscovering these on 4 Nov; a brief without them is not ready.*

## Small fixes

`small_fix=true` allows a one-line brief as long as it carries an accept command; it needs no ticket:

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
