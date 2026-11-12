# Brief template

Every `start_worker` brief (inline `brief` or `task_file`) must carry the seven labelled fields below. A start
missing any of them is refused with `brief_incomplete`, naming the missing ones.

**Project rule (Shivam, 4 Nov 2026):** the controller gathers everything the worker needs BEFORE the start. A worker
should spend its calls on the change, not on finding out what the brief left unsaid. On 4 Nov workers spent 50+ calls
before their first edit, about half of them database queries rediscovering facts the controller already had. A brief
is ready only when a worker could make its first edit within about 10 calls.

Goal: *one outcome, 1-3 lines: what is true when this is done, in terms of observable behaviour or rows.*

Evidence: *everything the worker would otherwise look up. Fill every item that applies; write "none" for the rest.*
- *Current behaviour: the exact rows, ids, values, doc_key + page, or command output that show the defect.*
- *Wanted behaviour: the rows or output that must appear instead (expected values, counts).*
- *Where: file, function and line for each change (find them with grep/read before writing the brief); the call
  path when the change crosses modules.*
- *Data: every table it will read with its columns, and the read-only paths (live dbs, D:\RealityEngine folders).*
- *Checks: the fast check command for each change (`build --part <part> --symbols <SYM>`, `checkpages run`, a single
  test file) with its current output and time, and which tests are slow (`-m "not slow"` for fix rounds).*
- *Gotchas already known: sandbox limits (pytest `tmp_path` denied in the dsh sandbox; use a temp dir under `.tmp`),
  names that mislead (e.g. `kpi_series` key is `id`, not `row_id`; `guidance` period column is `fiscal_period`), and
  any decision already made that the worker must not reopen.*

Files: *exact paths to change, and which are new. Add a "Do not touch" list for files another task owns.*

Accept: *numbered, testable accept checks, each naming the command or the observable result. This is the definition of
done. (`Test command(s):` may replace this label.)*

Stop if: *the conditions that must stop the work and report instead, e.g. a change needs files outside the named list.*

Budget: *tool calls before the first edit (default 15 when the Evidence is complete), total tool calls, paid $, wall
time. "No paid calls" when true.*

Ticket: *the row this work closes: `Ticket: T-014`, or `No-ticket: <reason>` when no open row fits. An unknown
T-number is refused with `ticket_unknown`; add the row first with `python -m reality_engine.scripts.task_board
add --section <section> --title "<title>" --why "<date and source>" --close-when "<check>" --accept "<runnable command>"`.*

## Small fixes

`small_fix=true` allows a one-line brief as long as it carries an accept command; it needs no ticket:

`Fix the typo in tasks/STATE.md. Accept: python -m pytest reality_engine/tests/test_dsh_worker_plugin.py -q`

## Report format

1. What changed (files, one line each).
2. How it was verified (commands + exact pass counts and times).
3. Anything the controller must install/run outside the worker sandbox.
4. Open problems.
5. Tool calls before first edit / total, and which Evidence item was missing or wrong (so the next brief improves).
6. Docs updated: every doc changed for this work, and each stale copy fixed or removed. A branch without this is not merged.

## Merge check (store diff, T-201)

A branch that rebuilds any part of a store is diffed by Opus before the merge with one command, on copies (the live
store is never touched):

```bash
python -m reality_engine.scripts.store_diff --store <db> --profile <json> \
  --parts transcripts,kpi,guidance,ratios --base main --head <branch|worktree path> --out <dir>
```

It rebuilds each named part with `main`'s code and with the branch's code from the same starting copy, diffs every
table by key, and exits 1 on a gate (a part that fails only on head, a lost `--golden` row, churn above
`--max-churn`). Details: `docs/DEVELOPER_GUIDE.md`, "Store diff before a merge (T-201)".

## Out of scope

*What the worker must not do, even if it looks related. Naming it prevents scope creep.*
