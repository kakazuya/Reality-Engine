Goal: stress-test and harden `reality_engine/scripts/job_watch.py wait` (T-050) and the Stop hook in `reality_engine/scripts/session_hooks.py`, so Claude is never left asleep while a finished dsh worker or job waits for review. Shivam's complaint: workers finish and Claude does not notice. Write `reality_engine/tests/test_job_watch_stress.py` with real subprocesses (run `python reality_engine/scripts/job_watch.py wait --poll-seconds 1` as a child process against a fixture `DSH_WORKER_RUNTIME_DIR`, a fixture `.tmp` state dir and a fixture git repo; add env overrides for the acks/wait/state paths if they do not exist yet) and fix every hole it finds. Scenarios, each must pass:
1. Race before baseline: a job finishes after Claude's last look but before `wait` takes its baseline, while another job is still running. Today the baseline swallows it and wait sleeps until the other job ends. Fix: at start, wait must exit at once and print any unreviewed FINISHED, NEEDS REVIEW / ENDED BADLY / STALLED line (flag `--ignore-existing` keeps the old behaviour).
2. A job flips running -> finished; wait exits within 2 poll intervals and prints the job id.
3. status.json half-written or invalid JSON during a poll (write garbage, then the real record): wait neither crashes nor exits falsely, and catches the finish once the record is valid.
4. 40 fixture jobs (30 old finished+acked, 10 running); one of the running ones finishes: it is reported even though more than 12 lines exist.
5. Registered job with no pid whose file stops changing: reported as STALLED after the stall window (make the window overridable for the test, e.g. env JOB_WATCH_REGISTERED_STALL_SECONDS).
6. Registered job with a pid that exits: reported as ENDED at the next poll.
7. Waiter killed hard (`kill`/TerminateProcess) leaves `.tmp/job_watch_wait.json`: Stop hook then sees no live waiter (pid dead) and blocks. Also guard pid reuse: record the process creation time with the pid and treat a different creation time as dead (Windows: psutil if installed, else ctypes GetProcessTimes; fall back to pid only).
8. Two waiters at once: one exiting must not make the other look dead (use one file per waiter pid, e.g. `.tmp/job_watch_wait/<pid>.json`, and `waiter_alive` = any live one).
9. Stop hook latency under 40 jobs: under 3 s.
10. `wait --timeout-seconds 3` with a job still running prints `TIMEOUT still running:` and exit code 0.
Docs: guide section L (job_watch) says what changed, including `--ignore-existing` and the per-waiter files.
Files: reality_engine/scripts/job_watch.py, reality_engine/scripts/session_hooks.py, reality_engine/tests/test_job_watch_stress.py, reality_engine/tests/test_job_watch.py, reality_engine/tests/test_session_hooks.py, docs/DEVELOPER_GUIDE.md
Accept: python -m pytest reality_engine/tests/test_job_watch_stress.py reality_engine/tests/test_job_watch.py reality_engine/tests/test_session_hooks.py -q
Stop if: a fix needs plugins/dsh-worker/ or .claude/settings.json changes; report it. Do not touch the live runtime folder, .tmp/job_watch*.json of the main checkout, or any real job.
Budget: 140 tool calls.
Ticket: T-053
Report: each scenario with pass/fail before your fix and after, changed files, test output, `Docs updated: <files>`.
