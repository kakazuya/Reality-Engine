# Brief — resource watchdog safe for this laptop (monitor-only for unapproved work)

> Worked example converted from `tasks/dsh_tasks/WATCHDOG_LAPTOP_2026-10-24.md` into
> `tasks/worker_context/BRIEF_TEMPLATE.md`. Every section below is required; the task content is unchanged.

## Goal
Make `resource_watchdog.py` safe on this laptop: it monitors jobs and cleans up orphans, but never restarts or
starts a managed job on the laptop profile, and never auto-starts a paid, GPU or PC-only job anywhere.

## Why
The watchdog was installed on the PC (2026-10-11) and has never run on this laptop (no logs, no Startup entry, no
process). Its restart behaviour would auto-start paid/GPU/PC-only work, which the standing rules forbid. Scheduled
tasks were disabled on 2026-10-21 at Shivam's request; data jobs now run through `plugins/dsh-worker/jobs.yaml`
(every job `enabled: false`). Without this fix, enabling the watchdog could spend money or start jobs that cannot
run here.

## Files to touch
- `reality_engine/scripts/resource_watchdog.py` — per-job `auto_restart` flag (default False), laptop profile
  (`REALITY_WATCHDOG_PROFILE=laptop` or a config file), laptop-aware disk checks, `--once --dry-run`, refusal of
  paid/GPU/PC-only jobs on the laptop profile.
- `reality_engine/tests/test_resource_watchdog.py` — new offline tests (restart skipped, refusals, orphan matching,
  incident writes, report render).
- Do not touch: any Startup folder entry, `plugins/dsh-worker/server/supervisor.py`, live databases, the
  `D:\RealityEngine` folder beyond the disk check, or anything else on `D:`.

## Inputs/data
- `reality_engine/scripts/resource_watchdog.py` header docstring (the `JOBS` registry, CHECK_SEC loop, incidents).
- Incident outputs: `reality_engine/data/logs/resource_watchdog.log`,
  `reality_engine/data/logs/resource_incidents.jsonl`,
  `reality_engine/data/logs/resource_watchdog_report.md` (read-only for tests; use temp fixtures).
- Machine facts: 8 cores, GTX 1050 Ti (not used), C: 460 GB SSD, D: 931 GB with only `D:\RealityEngine\` ours,
  Python 3.14 without `onnxruntime`.
- Standing rules: no paid API and no GPU work without Shivam's explicit OK; scheduled tasks stay disabled;
  `plugins/dsh-worker/jobs.yaml` ships every job `enabled: false`.

## Steps
1. Inventory every job the watchdog starts (including the daily new-reader check after 09:00, rclone and
   embedding re-runs): what it runs; paid / GPU / network-heavy / PC-only; whether it still exists in the repo.
2. Add a per-job `auto_restart` flag (default False) and a machine profile so the laptop restarts or starts
   nothing; record `job_stopped`/`job_hung` incidents instead. Keep waste monitoring and orphan cleanup, with
   orphans matched only inside this project folder.
3. Refuse to auto-start any paid, GPU or PC-only job on the laptop profile, even if its flag is flipped; log the
   reason.
4. Make disk checks cover C: and the `D:\RealityEngine` folder with thresholds documented for 8 cores; touch
   nothing else on `D:`.
5. Add `--once --dry-run`: one check, print intended actions, act on nothing.
6. Do not install the Startup entry or start the long-running watchdog (the sandbox cannot write the Startup
   folder); give Claude the exact install/start commands.

## Acceptance checks
1. `python -m unittest reality_engine.tests.test_resource_watchdog` exits 0 with the new tests included.
2. On the laptop profile, no managed job is restarted or started; `job_stopped`/`job_hung` incidents are written.
3. A paid, GPU or PC-only job refuses to auto-start on the laptop profile and logs the reason.
4. Orphan detection matches only processes whose command line/path is under this project folder.
5. `python reality_engine/scripts/resource_watchdog.py --once --dry-run` prints the actions it would take and
   changes nothing (exit 0).
6. No Startup entry is created and no long-running process is left behind by the worker.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_resource_watchdog
python -m unittest discover -s reality_engine/tests -p "test_*.py"
python reality_engine/scripts/resource_watchdog.py --once --dry-run
```

## Budget
≤ 25 tool calls before the first edit; ≤ 120 total; ≤ 60 min wall; $0 paid calls.

## Report format
1. What each job is and its new setting.
2. Code diff summary and chosen thresholds.
3. Test output and the `--once --dry-run` output on this laptop.
4. Exact install/start commands for Claude.
5. Tool calls before first edit / total.

## Out of scope
- Starting or installing the watchdog, editing the Startup folder, or re-enabling any scheduled task.
- Changing `plugins/dsh-worker/jobs.yaml` entries or their `enabled` flags.
- Touching other files on `D:`, GPU work, or paid API calls.
