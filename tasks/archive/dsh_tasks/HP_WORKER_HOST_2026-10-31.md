# Task — make the HP laptop host real dsh workers, and check OCR quality

## Goal
The capacity test says the HP can hold 6–8 workers. Make that real: the controller on the MSI starts a brief on the HP, it runs to the end unattended, and a reviewable patch comes back. Read first: `tasks/efficiency/HP_ACCEL_BENCH_2026-10-31.md`, `reality_engine/scripts/hp_run.py`, and the machine notes in `tasks/dsh_tasks/HP_RUNNER_AND_ACCEL_2026-10-31.md`.

## Fence (full-access run; the brief is the limit)
- On the MSI write only your worktree. On the HP write only `C:\RE`, user-level installs, and `~\.bun\bin`.
- Never print, log or copy `OPENCODE_GO_API_KEY_2`. It is already a user env var on the HP.
- Nothing from `Manual Dumps/` goes to the HP. No firewall, antivirus, account or power changes.
- Do not change lease, permission, write-scope or peak-hour logic in `plugins/dsh-worker`.

## Work
1. **Host setup on the HP:** Python 3.13 ARM64 for the MCP servers (`cryptography` has no cp314 win_arm64 wheel), a Node-backed `dsh` shim at `~\.bun\bin\dsh.exe` (Bun cannot boot dsh; Node 24 win-arm64 does), `git` on PATH (it is at `C:\Program Files\Git\cmd\git.exe`), and the code-intel and reality-data servers. Verify both servers answer a real call.
2. **`reality_engine/scripts/hp_worker.py`:** `start <brief.md> [--dbs a.db,b.db] [--test-cmd ...]`, `status`, `result <id>`, `fetch-patch <id>`, `cancel <id>`.
   - The MSI repo is shallow, so no remote worktrees from it. Each job gets `C:\RE\jobs\<id>\`: a fresh `git archive HEAD` of the commit given, with a throwaway local `git init` + base commit. The patch is the diff against that base, fetched back and applied to a `dsh-hp/<id>` branch on the MSI for normal review.
   - Launch detached via the WMI route proved in `hp_run.py`; use the harness with the same model, max effort and stable session ids. Peak-hour rule: refuse new starts in peak windows as the MSI does.
   - DBs: copied once to `C:\RE\data`, opened read-only by jobs, resynced only when the MSI copy is newer.
   - Use the same `CODE_INTEL_INSTRUCTION` and context pack as MSI workers.
3. **Prove it:** run 2 real small workers at once end to end, for example adding a docstring-only test note, and apply the patches on throwaway branches. Report peak RAM per real worker and any heartbeat or tool failure. Then 6 at once on short read-only tasks: real RAM, CPU, and time vs 1 worker. Keep model use small.
4. **OCR quality check, HP NPU.** Agreement with CPU at 0.971 does not prove accuracy, because the numpy post-processing gave gibberish earlier. Take 20 scanned pages and report for each: the first 200 characters of NPU output, and your reading of the page image. For pages with a text layer among non-scanned PDFs (use 20), compare OCR against the true text layer and report character accuracy. If accuracy is under 95% on clean pages, find out why and fix the post-processing. Do not run the full 1,073 files.

## Output
Append to `tasks/efficiency/HP_ACCEL_BENCH_2026-10-31.md`: real-worker capacity, the OCR accuracy table, and how to start a job.

## Acceptance checks
- Two real workers finished on the HP and produced patches that apply cleanly on the MSI.
- A job survives closing the SSH session.
- OCR accuracy measured against text-layer truth on 20 pages.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_hp_worker.py reality_engine/tests/test_hp_run.py -q
```
