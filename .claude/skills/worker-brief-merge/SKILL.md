---
name: worker-brief-merge
description: Brief a code worker (dsh DeepSeek, agy Hydrogen) prescriptively, then review and merge its branch with docs, tests and the review log. Use whenever handing code work to a worker or when job_watch shows "FINISHED, NEEDS REVIEW".
---

# Brief -> review -> merge

## Choose the worker
DeepSeek (dsh) off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST); Hydrogen (agy) any hour, each job to whoever does it better; max 4 code workers; read-only for audits. Every start names `permission`.

## Brief template (scout first: Opus finds the rows, file:line and a fast check)
```
Goal: <one line>. T-<ticket>.
Evidence: <rows / file:line / counts / report path to read first>
Steps: 1..n (numbered, each checkable)
Files: <only these>
Accept: <test_cmd passes> + <measured check, e.g. fingerprint unchanged>
Stop if: <condition>: report and stop.            (e.g. a rule changes > 3% of verified rows)
Pitfalls: run tests with PYTEST, not unittest (unittest skips pytest functions; fix 3 shipped a break that way);
  never write under C:/RealityEngine or D:/RealityEngine; regexes via the file editor; no model calls.
Budget: <minutes>.  Ticket: T-<n>
```
`test_cmd`: `python -m pytest -q <files>` — per file, not the whole suite (RAM).

## Review
Read `worker_result` (never result.md via grep), then the diff. Run the tests yourself, then your own sample on real data (the worker's self-check overstates). Fix small defects yourself in the worktree and say so in the review row.

## Merge (main checkout)
```
git merge --no-ff --no-commit <branch>; git rm -q --cached PROGRESS_NOTES.md; rm -f PROGRESS_NOTES.md
python -m pytest -q <files>
```
Append a `tasks/efficiency/worker_reviews.jsonl` row (id, ticket, stage, reviewer, verdict, evidence, lesson), add or update the STATE line (STATE <= 4,000 chars), docs updated in the same merge (no docs, no merge), and a commit message naming the ticket and ending `By: Wolf` (or Eagle).
Then `git worktree remove --force <wt>`, `git branch -D <branch>`, `python reality_engine/scripts/job_watch.py ack <job> --note merged`, and tell the other manager in 2–3 lines.
