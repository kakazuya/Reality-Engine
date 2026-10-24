# Task: make the resource watchdog safe for this laptop (monitor-only for unapproved work)

Owner: Shivam (2026-10-24). Reviewer: Claude (reviews your tests, merges, then installs and starts it).

## Context

- `reality_engine/scripts/resource_watchdog.py` (header docstring explains it): every CHECK_SEC it (a) keeps each
  managed job in `JOBS` alive by restarting it with its last command line if it stopped or its log went silent,
  (b) kills orphaned multiprocessing workers in this project folder, (c) records waste incidents (disk_hog, cpu_hog,
  low_ram, job_slow, job_hung/job_stopped, orphans_killed, restart_limit) to `reality_engine/data/logs/`
  (`resource_watchdog.log`, `resource_incidents.jsonl`, `resource_watchdog_report.md`). A Claude Code SessionStart
  hook prints the report. It starts at logon from the Windows Startup folder (`install_startup()`), or via
  `wscript reality_engine\scripts\run_hidden.vbs reality_engine\scripts\run_resource_watchdog.cmd`.
- It was installed on the PC (2026-10-11). On this laptop it has never run: no logs, no Startup entry, no process.
- This laptop: 8 cores, GTX 1050 Ti (not used for our jobs), C: 460 GB (SSD) + D: 931 GB personal data disk
  (`D:\RealityEngine\pdfs` is ours). Python 3.14 here lacks onnxruntime (GPU embedding jobs cannot run anyway).
- Standing rules: no paid API work and no GPU work starts without Shivam's explicit OK; scheduled tasks were
  disabled on 2026-10-21 at Shivam's request; data jobs now go through the dsh-worker job runner (`plugins/dsh-worker/jobs.yaml`,
  every job `enabled: false`).

## Do

1. Inventory `JOBS` (and anything else the watchdog starts, e.g. the daily new-reader check after 09:00, rclone,
   embedding re-runs). For each: what it runs, whether it is paid / GPU / network-heavy / PC-only (paths that don't
   exist here, D:\ paths, D: drive assumptions), and whether it still exists in the repo.
2. Make restarts opt-in: add a per-job `auto_restart` flag (default False) and a machine profile (env
   `REALITY_WATCHDOG_PROFILE=laptop` or a config file) so on the laptop **no managed job is restarted or started**;
   the watchdog only monitors them and records job_stopped/job_hung as incidents. Keep all waste monitoring and
   orphan cleanup (orphans only inside this project folder, as today). Any job that is paid, GPU or PC-only must
   never auto-start here even if someone flips its flag (refuse with a logged reason).
3. Make it laptop-aware: disk checks cover C: and the D:\RealityEngine folder; thresholds sensible for 8 cores
   (document the values you choose). Don't monitor or touch anything else on D:.
4. Tests (unittest, no network, no real process kills): restart is skipped on the laptop profile; paid/GPU/PC-only
   jobs refuse; orphan detection only matches processes under the project folder; incidents are written; the
   report renders. Run them and the existing quick suite.
5. A dry-run mode (`--once --dry-run`) that does one check and prints what it would do, without acting.
6. Do NOT install the Startup entry or start the long-running watchdog yourself (your sandbox can't write the
   Startup folder). Give Claude the exact two commands to install and start it.

## Final answer

What each job is and its new setting, the code diff summary, thresholds, test output, the `--once --dry-run` output
on this laptop, and the install/start commands.
