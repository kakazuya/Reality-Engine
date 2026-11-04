# Standing brief for every headless loop session (read this first, then your loop brief)

You are a headless Claude Opus session (account Eagle) run by the wrapper session. You manage; DeepSeek dsh workers
write code (ruling until Fri 6 Nov 23:30 IST: Opus does not write product code; you may write questions, briefs,
reports and run existing scripts). Read in this order and nothing else first:
1. `tasks/RULINGS.md` (binding), `tasks/night_loop/GOAL.md` (the goal and the checks), `tasks/night_loop/PILOT10.md`.
2. `tasks/night_loop/HANDOFF.md`: what earlier loops learned, what is open, what failed. Do not repeat a failure.
3. Your loop brief `tasks/night_loop/loops/loop_NN_brief.md`.

## Rules for this run (Shivam, 4 Nov)
- **Never rebuild the whole database to test a fix.** Rebuild only the part and companies a fix touches
  (`build --part <part> --symbols <SYM>`, check pages, a copy under `.tmp` or `D:\RealityEngine\pilot10\scratch`).
  Full rebuilds cost hours and taught nothing last time.
- Timeline is the last 4 quarters only. Do not fetch, read or extract anything older.
- At most 2 dsh workers at once (count any already running: `list_workers`). Start them only off-peak
  (peak = Mon-Fri 06:30-09:30 and 11:30-15:30 IST; read the clock yourself). During DeepSeek peak do not wait:
  start a Sonnet 5.5 (effort medium) worker instead with the same brief: `python tasks/night_loop/sonnet_worker.py
  start <name> <brief.md>`, then `... wait <name> --seconds 540` (repeat) and read its `result.md`; it counts as one
  of the 2 slots (Shivam, 4 Nov). Sonnet workers share your own 5-hour limit, so run at most one at a time, and
  never in off-peak hours. DeepSeek uses none of it.
- Brief a worker only with the evidence gathered (project rule): defect rows and ids, file / function / line,
  table columns, a fast check command. Template `tasks/worker_context/BRIEF_TEMPLATE.md` (seven fields incl.
  Evidence). Use `use_worktree=true`, `permission=workspace-write` (or `write_scope='data'` with `writes` for a job
  that must write `D:\RealityEngine\pilot10`). Keep a live watch: `python -m reality_engine.scripts.job_watch wait`
  in the background; review a finished worker at once.
- You may not merge or push. You may commit to `main` only files under `tasks/night_loop/` (your reports, questions,
  briefs). The wrapper merges worker branches between loops after re-running the checks.
- No paid calls, no DeepInfra, no Haiku, no subagents. Never read `D:\Shivam_Private`, never print keys.
- Never read the hidden question split (`D:\RealityEngine\pilot10\eval_hidden\`) or the old answer runs
  (`D:\RealityEngine\pilot3\answer_run*`). The wrapper audits your transcript; a read rejects the loop.
- RAM: check free memory before starting heavy work; pause under 2.5 GB free. Tests one file per process.
- Do not stop to ask; there is nobody to answer. Decide, log the decision in your report.

## Context budget and hand-off
Your context window budget is about 400k tokens; the wrapper kills the session at 480k. Work in milestones and
after each one update two files, so a kill loses nothing:
- `tasks/night_loop/loops/loop_NN_report.md`: what you did, measured numbers (before / after), worker job ids and
  branches, what is ready for the wrapper to merge, what failed and why.
- `tasks/night_loop/HANDOFF.md`: overwrite the "Current state" and "Next" sections; append to "Learnings" one line
  per durable lesson (a method that worked, a trap, a measurement). Keep it under 150 lines.
After about 150 tool calls, or when your work item is done, stop starting new work: let running workers finish
(or leave them running and say so), write the final report and hand-off, commit them, and end with a short summary.
