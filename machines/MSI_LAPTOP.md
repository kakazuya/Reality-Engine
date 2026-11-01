# MSI laptop

Main machine, hostname `Sumit`. Runs Claude, dsh workers, merges, GPU work and source data. Personal broker files stay here only, outside the workspace, in `D:\Shivam_Private\Manual Dumps`.

## Workers
- At most 2 code workers at once (`tasks/RULINGS.md`), with at least 2.5 GB free. Uses Go account 2 by default.
- `start_worker` requires `permission` explicitly (`workspace-write` to write, `read-only` to read); a start without it is refused as `permission_required`. Read `permission` in the start result. The gate is in `plugins/dsh-worker/server/plugin_server.py` and `plugins/dsh-worker/server/core.py`.
- Every brief must carry `Goal:`, `Files:`, `Accept:` (or `Test command(s):`), `Stop if:` and `Budget:`; a missing field refuses the start as `brief_incomplete`. `small_fix=true` allows a one-line brief with an accept command. The check is in `plugins/dsh-worker/server/core.py` and `plugins/dsh-worker/server/context_pack.py`.
- The supervisor renews the lease by itself while the worker lives, so a forgotten renewal no longer kills a long job. `hard_timeout_seconds` defaults to 4 h (14400 s) and is the real limit; an explicit `controller_lease_seconds` (max 2 h) only sets the controller window, and `renew_worker_lease` is for ownership/takeover. Implemented in `plugins/dsh-worker/server/supervisor.py`.
- A dead supervisor still ends the job: its `KILL_ON_JOB_CLOSE` job object owns the worker.
- Ending worktree jobs commit their non-empty diff; failed, cancelled, lease-expired and timeout jobs use the subject prefix `WIP ended <reason>:`.
- Closing the session that owns a worker can kill it.
- Merged worktrees get removed, since each holds a large search cache.

## Worker context pack
The generated pack is `tasks/worker_context/CONTEXT.md`: about 5.7 KB (limit 20,000 bytes). It is an index, not a repo map: code-intel and reality-data lookup commands, test selection, sandbox limits, conventions, and a pointer to `tasks/STATE.md`.
- `reality_engine/scripts/build_worker_context.py` — builder, trimmed to the lookup sections, writes the pack and `schemas/<db>.md`.
- `reality_engine/tests/test_worker_context.py` — fails when the built pack exceeds 20,000 bytes.
- `reality_engine/tests/test_dsh_worker_plugin.py` — `WorkerContextBuilderTests` checks the sections and the byte limit.

## Hardware
NVIDIA GTX 1050 Ti with 4 GB, 8 CPU threads. Use CUDA, and check `nvidia-smi` before GPU plans. GPU OCR is slower than CPU here.

## Storage
Raw data goes on `D:\RealityEngine`. C holds operations and processed databases. Avoid sustained heavy disk work.

