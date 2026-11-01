# MSI laptop

Main machine, hostname `Sumit`. Runs Claude, dsh workers, merges, GPU work and source data. Personal broker files in `Manual Dumps/` stay here only.

## Workers
- 2 to 3 workers, with at least 2.5 GB free. Uses Go account 2 by default.
- `start_worker` needs `permission="workspace-write"` to write, as it defaults to read-only. Read `permission` in the start result.
- Leases default to 30 minutes and are at most 2 hours. They never renew themselves, and expiry kills the worker: use `controller_lease_seconds=7200` and renew.
- Closing the session that owns a worker can kill it.
- Merged worktrees get removed, since each holds a large search cache.

## Worker context pack
The generated pack is `tasks/worker_context/CONTEXT.md`: 5,631 bytes (limit 20,000, about 1.4k tokens). It is an index, not a repo map: code-intel and reality-data lookup commands, test selection, sandbox limits, conventions, and a pointer to `tasks/STATE.md`.
- `reality_engine/scripts/build_worker_context.py` — builder, trimmed to the lookup sections, writes the pack and `schemas/<db>.md`.
- `reality_engine/tests/test_worker_context.py` — new guard that fails when the built pack exceeds 20,000 bytes.
- `reality_engine/tests/test_dsh_worker_plugin.py` — `WorkerContextBuilderTests` updated to the new sections and the byte limit.

## Hardware
NVIDIA GTX 1050 Ti with 4 GB, 8 CPU threads. Use CUDA, and check `nvidia-smi` before GPU plans. GPU OCR is slower than CPU here.

## Storage
Raw data goes on `D:\RealityEngine`. C holds operations and processed databases. Avoid sustained heavy disk work.
