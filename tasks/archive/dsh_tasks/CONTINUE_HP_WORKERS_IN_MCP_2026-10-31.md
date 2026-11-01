# CONTINUE: the earlier run was killed mid-task on 31 Oct at about 05:17 IST (supervisor and worker both gone, most likely when the session that owned it closed)

This worktree already holds YOUR partial work from that run, uncommitted. Before anything else:
1. Read `.tmp/PROGRESS_NOTES.md` (or root `PROGRESS_NOTES.md`) if present, then `git status` and `git diff --stat`.
2. Keep what is correct. Re-run only the steps that did not finish. Resume long jobs from existing outputs and `.tmp` DBs instead of starting over.
3. Check for leftovers of the killed run before starting anything long: stray python processes on the MSI, and any HP processes this task started (the HP is `zen7s@192.168.1.42`; another worker's job `hp-20261031T051124-3e6065` is running there, never touch it).
4. Finish the original brief below and give its full report. Do not commit: the reviewer commits this worktree after review.
5. RAM is tight on the MSI: at most one heavy process at a time. If `REALITY_DATA_ROOT` is unset, read data from `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data`, read-only.

---
# Task — show and control HP workers from the dsh-worker MCP, and test throughput

## Goal
Shivam wants to see workers running on the HP laptop alongside MSI workers: in `list_workers`, `worker_status`, `worker_result`, and the `/dsh-workers` pane. Today HP jobs exist only through `reality_engine/scripts/hp_worker.py`.

## Work
1. **Find how the `/dsh-workers` pane gets its data** (it may read `plugins/dsh-worker/runtime/jobs/*/status.json` or call the server) and make HP jobs appear there, labelled `HP`, with no change to how it starts.
   - Simplest acceptable design: `hp_worker.py start` writes a job record in the same runtime format with `host: "hp"`, and a light poller refreshes status over SSH. Reads must never hang on the network: use a cache with a timeout, and show `HP unreachable, last seen HH:MM` when the laptop is off.
2. **MCP:** `list_workers` and `worker_status` show HP jobs in the same compact form with `host`. `worker_result` returns the HP result. `cancel_worker` works on HP jobs with `confirm=true`. Add `start_worker(host="hp")` routed to `hp_worker.py`, defaulting to the MSI.
   - No change to lease, permission, write-scope or peak-hour logic for MSI jobs. HP jobs must respect the same peak-hour refusal and have a lease-like hard stop.
3. **Accounts:** HP workers default to Go account 1 (`OPENCODE_GO_API_KEY`, already a user env var on the HP), with `--account` to override. MSI stays on account 2. Never print or log a key.
4. **Host address:** default `HP_RUN_HOST=zen7s@192.168.1.42`, falling back to `100.78.87.112`.
5. **Throughput test.** Six HP workers ran a short task 4.5× slower than one, with CPU only 13–26%. Find out why: run the same small real task with 1, 3 and 5 workers on account 1 at the same moment as noting free RAM, and record each worker's time split into model wait vs local time from its events. Say whether the limit is the provider, memory or local, and the worker count that gives the most finished work per hour. Keep model use small.

## Fence (full-access run; the brief is the limit)
On the MSI write only your worktree. On the HP write only `C:\RE` and its job folders. Nothing from `Manual Dumps/` goes to the HP. No firewall, antivirus, account or power changes.

## Acceptance checks
- A real HP job appears in `list_workers` and the pane data while running and after finishing; a test covers the HP-unreachable path, which returns within 3 seconds.
- The controller can start, read and cancel an HP job through MCP tools.
- Throughput table written to `machines/HP_ACCEL_BENCH_2026-10-31.md`, with a recommended worker count.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_dsh_worker_plugin.py reality_engine/tests/test_hp_worker.py -q
```

## Report
Include restart steps for the controller and code-intel calls vs grep/read/pwsh.

