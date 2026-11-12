# MSI laptop

Main machine, hostname `Sumit`. Runs Claude, dsh workers, merges, GPU work and source data. Personal broker files stay here only, outside the workspace, in `D:\Shivam_Private\Manual Dumps`.

## Workers
- At most 2 code workers at once (`tasks/RULINGS.md`); `start_worker` now refuses the third with `code_worker_limit` (read-only and `host='hp'` starts are not counted), gate in `plugins/dsh-worker/server/core.py`. Keep at least 2.5 GB free. Uses Go account 2 by default.
- `start_worker` requires `permission` explicitly (`workspace-write` to write, `read-only` to read); a start without it is refused as `permission_required`. Read `permission` in the start result. The gate is in `plugins/dsh-worker/server/plugin_server.py` and `plugins/dsh-worker/server/core.py`.
- Every brief must carry `Goal:`, `Files:`, `Accept:` (or `Test command(s):`), `Stop if:` and `Budget:`; a missing field refuses the start as `brief_incomplete`. `small_fix=true` allows a one-line brief with an accept command. The check is in `plugins/dsh-worker/server/core.py` and `plugins/dsh-worker/server/context_pack.py`.
- The supervisor renews the lease by itself while the worker lives, so a forgotten renewal no longer kills a long job. `hard_timeout_seconds` defaults to 4 h (14400 s) and is the real limit; an explicit `controller_lease_seconds` (max 2 h) only sets the controller window, and `renew_worker_lease` is for ownership/takeover. Implemented in `plugins/dsh-worker/server/supervisor.py`.
- A dead supervisor still ends the job: its `KILL_ON_JOB_CLOSE` job object owns the worker.
- Ending worktree jobs commit their non-empty diff; failed, cancelled, lease-expired and timeout jobs use the subject prefix `WIP ended <reason>:`.
- Closing the session that owns a worker can kill it.
- Merged worktrees get removed, since each holds a large search cache.

## reality-data store routing (T-203, 12 Nov 2026)
`plugins/reality-data/server/lookups_pilot3.py` resolves each `pilot3_*` call to the registered store that holds
the symbol (`REALITY_PILOT3_STORES`, default `D:/RealityEngine/stores.json`); `core.py` (`db_path`,
`connect_pilot3`, `connect_sqlite`), `server.py` (`catalog`/`schema`/`pilot3_sql` `store=`), `catalog.py`,
`reality_engine/scripts/store_registry.py` (generator) and `reality_engine/scripts/p3ask.py` (`--db` optional)
carry it. `REALITY_PILOT3_DB` pins one store. Test: `plugins/reality-data/tests/test_store_routing.py`.

## Worker context pack
The generated pack is `tasks/worker_context/CONTEXT.md`: about 5.7 KB (limit 20,000 bytes). It is an index, not a repo map: `code-tools` outline/typecheck and reality-data lookup commands, test selection, sandbox limits, conventions, and a pointer to `tasks/STATE.md`.
- `reality_engine/scripts/build_worker_context.py` — builder, trimmed to the lookup sections, writes the pack and `schemas/<db>.md`.
- `reality_engine/tests/test_worker_context.py` — fails when the built pack exceeds 20,000 bytes.
- `reality_engine/tests/test_dsh_worker_plugin.py` — `WorkerContextBuilderTests` checks the sections and the byte limit.

## Hardware
NVIDIA GTX 1050 Ti with 4 GB, 8 CPU threads. Use CUDA, and check `nvidia-smi` before GPU plans. GPU OCR is slower than CPU here.

Local vision models do run on it (T-188, 11 Nov 2026): llama.cpp release **b12284** in `D:/RealityEngine/tools/llamacpp/`
(CUDA **13.5** dies on Pascal with `ggml-cuda.cu:113: CUDA error`; CUDA **12.4** works, `offloaded 19/19 layers to GPU`),
weights in `D:/RealityEngine/models/` (recorded in `models/MODELS.md`), runner `reality_engine/v2/local_reader.py`
(`llama-server` hidden, `-c 8192 -np 1 -ngl 99 --temp 0 -lv 4`, 1.9-3.0 GB VRAM peak, 12-92 s a page for a 0.9B Q8_0
page reader). `-b 1`/`-ub 1` breaks the vision encoder, so the default ubatch stays. Docs:
`docs/V2_SCHEMA_CONTRACT.md` section 14.

## Storage
Raw data lived on `D:\RealityEngine`; since T-102 (7 Nov 2026) the raw files are uploaded to `gdrive:InfoDiffusion_archive` (`msi_raw/<root>/<rel>`, manifest `D:\RealityEngine\drive_index\raw_to_drive.db`) and the local copies are deleted by `raw_to_drive.py delete` (`D:\RealityEngine\raw\user_research` stays local). Jobs read them on demand through `reality_engine/raw_store.py`: one `rclone copy --files-from` per company into a temp folder, md5-checked and deleted after, so a build works with no raw files on disk. C holds operations and processed databases. Avoid sustained heavy disk work.

