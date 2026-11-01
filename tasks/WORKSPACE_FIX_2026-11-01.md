# Workspace fix, approved by Shivam 1 Nov 2026

The workspace gets fixed before database design. OCR and extraction wait until step 4 passes. Estimate 1.5 days. Keep it lean: nothing is added here unless it stops a failure we have already had.

## Two files
- **Question map:** one row per bank question: measure, formula, store, pass or fail. Only a check script flips the result. It is also the backlog and the schema design table.
- **Six-line brief:** goal and question rows, files to use, accept command, stop rule, budget. Small fixes get one line.

## Three code gates
1. **Start:** `start_worker` refuses a brief missing those fields, requires an explicit permission, and renews leases itself.
2. **Merge:** tests, doc gate, the accept check, a hidden evaluation for graded work, and a diff against Shivam's rulings.
3. **Reading:** the 84 KB context pack shrinks to about 5k tokens. Add a hard read limit only if the median stays above 10 calls before first edit.

## Three limits
- At most 2 code workers at once. Research and data jobs do not count.
- Every finished branch is merged or deleted within 24 hours.
- A new rule needs a repeat failure and its own check. `AGENTS.md` stays under 150 lines.

Claude: `PreToolUse` hook and permission settings keep it out of `tasks/archive`. Workers commit progress when stopped or killed, not only on success.

## Steps
| # | Work | Exit test | Status |
|---|---|---|---|
| 1 | Clear unmerged branches, commit `main` | 0 work in limbo | Running |
| 2 | Start gate, smaller pack | A bad brief is refused; pack about 5k tokens | |
| 3 | Merge gate, cut `AGENTS.md` | Deliberate violations are blocked; under 150 lines | |
| 4 | Question map for the 3 prototype companies | Every bank question naming them has a row | |

## Success test
Over the next 10 jobs: median 10 or fewer calls before first edit (today 20 across 129 jobs, maximum 75), no branch older than 24 hours, no repeat read-only or lease failures. If that fails, add the read limit and nothing bigger.
