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

## Factor studies (T-210, 14 Nov 2026)
`reality_engine/research/factor_deep.py` + `reality_engine/tests/test_factor_deep.py` (13 synthetic tests) deepen the T-207 reward study: per-sector rewarded sets, exposure/IC pair correlations and clusters, per-company empirical-Bayes shrinkage, sector Fama-MacBeth redundancy, 595-pair tercile interactions with a 20-permutation gate, sparse stepwise combinations, and a pilot-store KPI arm. Report `docs/research/T-210_factor_deep_study.md`. Full panel run needs >= 7 GB free RAM (DuckDB snapshot build); it did not start on 14 Nov because 89 one-minute samples (00:12-01:42) ranged 2.6-4.7 GB with three workers running.

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

## Reality-data tool replies (T-197, 12 Nov 2026)
- `plugins/reality-data/server/lookups_pilot3.py` — shared `coverage` / paging (`offset`) / `read_next` / `_shrink` reply-cap helpers, page-text reach for `topic` and `statements`, `cells` values, `docs` list paging, `as_of` hidden-document report.
- `plugins/reality-data/server/lookups_semantic.py` — `offset` + coverage on the semantic ranking.
- `plugins/reality-data/server/server.py` — `offset` on the six text tools and the general answer rules in the server instructions.
- `reality_engine/pilot3/events.py` + `schema.py` — `event.doc_type` / `title` / `body_excerpt` (migration v9 in `schema.py`, T-202: the build part no longer adds them) and `lexicon/{common,pharma,metals}.yaml` `event_cues`.
- `reality_engine/scripts/p3ask.py` — the reply-reading rules in its help.

## Schema version and migrations (T-202, 12 Nov 2026)
- `reality_engine/pilot3/schema.py` — `schema_meta.schema_version` / `migrated_at`, the numbered additive `MIGRATIONS` list (v9 = T-197's event columns, v10 = T-199's `page_atom` table and indexes), `migrate` / `version` / `pending`, and the `--status|--migrate` CLI.
- `reality_engine/pilot3/build.py` + `stores.py`, `ratios.py`, `guidance.py`, `transcripts.py`, `events.py`, `kpi.py`, `xbrl_segments.py`, `preferred.py`, `row_checks.py` — one `schema.migrate(conn)` at the start of a build run (and in a part run straight from a script); the old per-part `ensure_columns` / `ensure` surgery is gone.
- `plugins/reality-data/server/lookups_pilot3.py` — `store_version()` (one cached read per routed store path), the `_has_column` version floors and `provenance.schema_version` / `schema_note`; a read-only server never migrates.
- `reality_engine/tests/test_pilot3_schema_version.py` — a version-0 store (18-column `share_capital`, no `guidance.entity`) and a v8/v9 store gain the columns/table in place with their rows unchanged, migrate twice is a no-op, and read-only lookups answer on a version-0 store.

## Page atoms (T-199, 13 Nov 2026)
- `reality_engine/v2/page_reader.py` — `export` (1,280-px image + exact `read_page` prompt, 8 per batch, `manifest.csv` / `duplicates.csv`, text-hash dedupe by earliest `known_at`), `--reader file:<DIR>` (reply files, `error: no reply`, `reader = haiku_sub`, no second pass), `needs_ocr` pages in both; a row's heading is written into `page_cell.row_label` as `<section> > <label>` only for a printed list marker or a label printed on two lines (round 3).
- `reality_engine/pilot3/atoms.py` — resolves each non-quarantined `page_cell` into `page_atom` (period/basis/unit/scale/value/definition, verified only when position-checked AND period+unit resolved, same-document conflicts, document-period fallback, change markers, duplicate copies); the row's label/header words decide the unit before the page declaration (ratio/times -> x, days -> days, margin/% -> pct, count nouns -> count with `count_unit=<word>`), a serial-number row or a year printed as a value makes no atom (round 3); `build.py` part `atoms` after `checks`.
- `reality_engine/v2/reference_pages.py` + `reference_vote.py` + `reference_geom.py` — `parse_grid` carries a section heading (`section`) and `_normalize_row` keeps it; `settle_page`/`place` keep equal values printed under two columns as two cells and carry `section` / `label_repeated` into `reference_cells.csv` (round 3).
- `plugins/reality-data/server/lookups_pilot3.py` — `cells`/`fact`/`kpi`/`topic` read `page_atom` first, with `page_cell` the fallback while a store has no atoms.
- Tests: `reality_engine/tests/test_pilot3_atoms.py` (32), `reality_engine/tests/test_v2_page_reader.py` (11, `--basetemp` needs `-p no:tmpdir` in the dsh sandbox), `reality_engine/tests/test_v2_reference_pages.py` (7), `reality_engine/tests/test_v2_reference_geom.py` (11), `plugins/reality-data/tests/test_lookups_pilot3.py` (82 + 1 skipped).

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

