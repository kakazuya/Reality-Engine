# Workspace fix, approved by Shivam 1 Nov 2026

The workspace was to be fixed before database design. **Shivam, 2 Nov: the issues are settled and the pilot test resumes; steps left here are tickets in `tasks/TASKS.md` and block nothing.** Estimate 1.5 days. Keep it lean: nothing is added here unless it stops a failure we have already had.

## Two files
- **Question map:** one row per bank question: measure, formula, store, pass or fail. Only a check script flips the result. It is also the backlog and the schema design table.
- **Six-line brief:** goal and question rows, files to use, accept command, stop rule, budget. Small fixes get one line.

## Three code gates
1. **Start:** `start_worker` refuses a brief missing those fields, requires an explicit permission, and renews leases itself.
2. **Merge:** tests, doc gate, the accept check, a hidden evaluation for graded work, and a diff against Shivam's rulings.
3. **Reading:** the 84 KB context pack shrinks to about 5k tokens. Add a hard read limit only if the median stays above 10 calls before first edit. Done 1 Nov: 5,631 bytes (about 1.4k tokens), guarded by `reality_engine/tests/test_worker_context.py` at 20,000 bytes; the read limit stays unset.

## Three limits
- At most 2 code workers at once. Research and data jobs do not count.
- Every finished branch is merged or deleted within 24 hours.
- A new rule needs a repeat failure and its own check. `AGENTS.md` stays under 150 lines.

Claude: `PreToolUse` hook and permission settings keep it out of `tasks/archive`. Workers commit progress when stopped or killed, not only on success.

## Context limits (Shivam, 1 Nov)
Every session must make steady progress without loading the repo. A session started at about 54k tokens in the last 5 sessions, before any work.
- **Short start:** `tasks/STATE.md` holds the current step, the exact next action, running jobs and blockers. A check keeps it under 40 lines. History goes to the decision log.
- **One step per session:** finish, commit and write the next action into `tasks/STATE.md`. Write the wrap-up at 400k tokens; the session limit is 450k (Shivam, 1 Nov, replacing 150k).
- **Results in files:** scripts print summaries, workers report one page, and details live in files read only when needed.
- **Fences:** `tasks/archive`, `.tmp` and data folders are blocked from Claude's reads and hidden from search unless a task names them.
- **Rules move into checks:** once a check enforces a rule, its memory entry and `AGENTS.md` text go away.

Checks in place: `reality_engine/scripts/doc_gate.py` refuses a `tasks/STATE.md` over 40 lines or an `AGENTS.md` over 150. `.ignore` hides archive, job and data folders from search, and `.claude/settings.json` denies reading archive, `.tmp` and job folders.

## Carrying rulings forward (Shivam, 1 Nov: his main problem)
Before this fix, no hook loaded anything. Memory held 69 files of 122 KB, but only a list of titles reached a session, and the bodies were read only if Claude chose to.
- `tasks/RULINGS.md`: his active rulings, under 40 lines. `reality_engine/scripts/load_context.py` loads it with `tasks/STATE.md` at every start and after every compaction, within the 10,000-character hook cap. `reality_engine/tests/test_load_context.py` guards this.
- A ruling or correction goes in the file before the next action. A rule that can have a check gets one. `reality_engine/scripts/build_worker_context.py` points workers at the file.
- **Test:** each repeat correction goes in the decision log and is counted. Shivam dropped the quiz on 2 Nov after reviewing the file.

## Enforcement order (Shivam asked, 1 Nov: do md rules even work?)
Written rules are the weakest layer. Use the strongest that fits: make the wrong action impossible (tool defaults, OS and file permissions), block it at the moment (`PreToolUse` hook, permission deny), refuse it at commit or merge (gates, tests), reject bad data at write time (typed contracts, database constraints), then an independent check. `tasks/RULINGS.md` is only for judgement rules and context.

Add in step 3, each from a failure we have had: hook blocks on `git push` without his OK, any read of `D:\Shivam_Private\Manual Dumps` (moved out of the repo on 1 Nov), keys printed to output, and edits to hooks or gates by agents; worker OS write roots excluding `Manual Dumps/`; a bank rebuild refused when ruled rows change; the full test suite refused on the MSI while workers run. As each check lands, shorten its line in `tasks/RULINGS.md` to `[check]`. Hook matching is best-effort, so hard denials use permissions as well.

## Steps
| # | Work | Exit test | Status |
|---|---|---|---|
| 1 | Clear unmerged branches, commit `main` | 0 work in limbo | Done 1 Nov: 9 merged, 12 kept as `archive/` tags, 93 merged branches and 20 worktrees removed |
| 2 | Start gate, smaller pack, context limits | A bad brief is refused; pack about 5k tokens; Claude starts from one short file | Done 1 Nov: pack 5,631 bytes, limit 20,000, test `reality_engine/tests/test_worker_context.py`; start gate merged; session limit 450k with the wrap-up at 400k via `reality_engine/scripts/context_guard.py` |
| 3 | Merge gate, cut `AGENTS.md` | Deliberate violations are blocked; under 150 lines | |
| 4 | Question map for the 3 prototype companies | Every bank question naming them has a row | Done 2 Nov: 286 rows, `tasks/pilot60/question_map/build_map.py` |

## Success test
Over the next 10 jobs: median 10 or fewer calls before first edit (today 20 across 129 jobs, maximum 75), no branch older than 24 hours, no repeat read-only or lease failures. If that fails, add the read limit and nothing bigger.
